# nix/desktop.nix — Robo Desktop (Electron) app build + wrapper
#
# `roboAgent` is the fully-built `.#default` package — it ships the
# `robo` binary with the venv, runtime PATH, bundled skills/plugins, etc.
# already wired up.  We point the desktop at it via the existing
# `ROBO_DESKTOP_ROBO` override env var, so the desktop's resolver
# uses our fully wrapped binary at step 4 ("existing Robo CLI").
# No reimplementation of the agent resolution in this wrapper.
{
  pkgs,
  lib,
  stdenv,
  makeWrapper,
  roboNpmLib,
  electron,
  roboAgent,
  python3,
  ...
}:
let
  electronHeaders = pkgs.fetchurl {
    url = "https://artifacts.electronjs.org/headers/dist/v${electron.version}/node-v${electron.version}-headers.tar.gz";
    sha256 = "sha256-f8bSbLRmtbP93CJAvEBs+sHWDZ1xP2bcpLhC1EnOmZU=";
  };

  # node-pty ships no Electron-tagged prebuild we can trust to match this
  # exact nixpkgs electron version, so it's always compiled from source
  # against Electron's own headers (not whatever Node ran `npm`).
  targetPlatform =
    if stdenv.hostPlatform.isDarwin then
      "darwin"
    else if stdenv.hostPlatform.isLinux then
      "linux"
    else
      throw "robo-desktop: unsupported host platform for node-pty staging";

  targetArch =
    if stdenv.hostPlatform.isAarch64 then
      "arm64"
    else if stdenv.hostPlatform.isx86_64 then
      "x64"
    else
      throw "robo-desktop: unsupported host arch for node-pty staging";

  # Build the renderer (dist/ + electron/ + package.json).
  renderer = roboNpmLib.buildNpmPackage {
    dirs = [
      "apps/desktop"
      "apps/shared"
    ];
    pname = "robo-desktop-renderer";

    doCheck = true;

    buildPhase = ''
      runHook preBuild

      mkdir -p apps/desktop/build

      patchShebangs .

      pushd apps/desktop
        # typecheck :3
        npm exec -- tsc -b

        # build the renderer bundle
        # vite's emptyOutDir wipes dist/ on every run
        # so it has to be first
        npm exec -- vite build

        # build the electron bundle
        node scripts/bundle-electron-main.mjs

        # Compile node-pty against Electron's actual ABI (the nixpkgs
        # `electron` we ship). Headers come from a pinned fetchurl input
        # since the sandbox has no network here, so node-gyp's
        # normal --disturl download path can't run.
        mkdir -p "$TMPDIR/electron-headers"
        tar -xzf ${electronHeaders} -C "$TMPDIR/electron-headers" --strip-components=1

        ${lib.getExe roboNpmLib.node-gyp} rebuild \
          --directory=../../node_modules/node-pty \
          --build-from-source \
          --runtime=electron \
          --target=${electron.version} \
          --nodedir="$TMPDIR/electron-headers" \
          --disturl="" \
          --offline

        # Target platform/arch come from stdenv.hostPlatform, not the
        # build host's own process.platform/arch.
        node scripts/stage-native-deps.mjs ${targetPlatform} ${targetArch}
      popd

      runHook postBuild
    '';

    checkPhase = ''
      runHook preCheck

      pushd apps/desktop

        npm run postbuild

        # validate staged node-pty native binary is present.
        STAGED_PTY_NODE="./dist/node_modules/node-pty/build/Release/pty.node"

        if [ ! -f "$STAGED_PTY_NODE" ]; then
          echo "FATAL: Missing staged node-pty native binary at $STAGED_PTY_NODE"
          echo "node-pty must be compiled natively"
          exit 1
        fi
        
      popd

      runHook postCheck
    '';

    installPhase = ''
      runHook preInstall
      mkdir -p $out
      # vite writes to apps/desktop/dist/ (we cd'd there in buildPhase).
      # stage-native-deps.mjs stages node-pty into dist/node_modules/node-pty,
      # so copying dist/ wholesale carries the native dep along with the
      # esbuild bundle that require()s it. apps/desktop/build was created
      # before the cd.
      cp -rn apps/desktop/dist $out/

      echo '{"schemaVersion":1,"commit":"nix-dummy-commit","branch":"nix","dirty":false,"source":"nix"}' > $out/install-stamp.json

      cp -n apps/desktop/package.json $out/
      runHook postInstall
    '';
  };
in

# Electron wrapper: nixpkgs' electron binary pointed at the renderer dir.
stdenv.mkDerivation {
  pname = "robo-desktop";
  inherit (renderer) version;

  dontUnpack = true;
  dontBuild = true;

  nativeBuildInputs = [
    makeWrapper
    python3
  ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/robo-desktop $out/bin
    cp -r ${renderer}/* $out/share/robo-desktop/

    # Standard nixpkgs pattern for electron-builder apps: patch process.resourcesPath
    # to point to the app's directory. In Nix, unpackaged electron defaults this
    # to the electron distribution's resources path, breaking extraResources lookups.
    substituteInPlace $out/share/robo-desktop/dist/electron-main.mjs \
      --replace-fail "process.resourcesPath" "'$out/share/robo-desktop'"

    # Wrap the nixpkgs electron binary to launch our app.  Set
    # ROBO_DESKTOP_ROBO to the absolute path of the nix-built `robo`
    # binary so the desktop's resolver step 4 ("existing Robo CLI on
    # PATH") uses our fully wrapped binary — venv with all deps,
    # bundled skills/plugins, runtime PATH (ripgrep/git/ffmpeg/etc).
    # No reimplementation of the agent resolver in the wrapper.
    makeWrapper ${lib.getExe electron} $out/bin/robo-desktop \
      --add-flags "$out/share/robo-desktop" \
      --set ROBO_DESKTOP_ROBO "${lib.getExe roboAgent}" \
      --set ELECTRON_IS_DEV 0

    # XDG launcher entry
    mkdir -p $out/share/applications $out/share/icons/hicolor/1024x1024/apps
    install -m 0644 ${../apps/desktop/assets/icon.png} \
      $out/share/icons/hicolor/1024x1024/apps/robo.png
    export PYTHONPATH=$(mktemp -d)
    cp ${../robo_cli/linux_desktop_entry.py} "$PYTHONPATH/linux_desktop_entry.py"
    export DESKTOP_EXEC="$out/bin/robo-desktop"
    export DESKTOP_ICON="$out/share/icons/hicolor/1024x1024/apps/robo.png"
    python3 -c 'import os; from linux_desktop_entry import render_desktop_entry; print(render_desktop_entry(os.environ["DESKTOP_EXEC"], os.environ["DESKTOP_ICON"]))' > $out/share/applications/robo.desktop
    runHook postInstall
  '';

  passthru = {
    inherit (renderer.passthru) packageJsonPath;
  };

  meta = with lib; {
    description = "Native Electron desktop shell for Robo Agent";
    homepage = "https://github.com/igniteenow/robo";
    license = licenses.mit;
    platforms = platforms.unix;
    mainProgram = "robo-desktop";
  };
}
