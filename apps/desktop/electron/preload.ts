import { contextBridge, ipcRenderer, webUtils } from 'electron'

contextBridge.exposeInMainWorld('roboDesktop', {
  getConnection: profile => ipcRenderer.invoke('robo:connection', profile),
  revalidateConnection: () => ipcRenderer.invoke('robo:connection:revalidate'),
  touchBackend: profile => ipcRenderer.invoke('robo:backend:touch', profile),
  getGatewayWsUrl: profile => ipcRenderer.invoke('robo:gateway:ws-url', profile),
  openSessionWindow: (sessionId, opts) => ipcRenderer.invoke('robo:window:openSession', sessionId, opts),
  openWindow: () => ipcRenderer.invoke('robo:window:openInstance'),
  claimAmbientCue: key => ipcRenderer.invoke('robo:ambient:claim', key),
  wakeIndicator: {
    getState: () => ipcRenderer.invoke('robo:wake-indicator:get'),
    setState: state => ipcRenderer.send('robo:wake-indicator:set', state),
    onState: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('robo:wake-indicator:state', listener)

      return () => ipcRenderer.removeListener('robo:wake-indicator:state', listener)
    }
  },
  petOverlay: {
    // Main renderer → main process: window lifecycle + drag. `request` is
    // `{ bounds, screen }`; resolves with the screen bounds it actually used.
    open: request => ipcRenderer.invoke('robo:pet-overlay:open', request),
    close: () => ipcRenderer.invoke('robo:pet-overlay:close'),
    setBounds: bounds => ipcRenderer.send('robo:pet-overlay:set-bounds', bounds),
    setIgnoreMouse: ignore => ipcRenderer.send('robo:pet-overlay:ignore-mouse', ignore),
    // Flip the overlay focusable (and focus it) while the composer needs keys.
    setFocusable: focusable => ipcRenderer.send('robo:pet-overlay:set-focusable', focusable),
    // Main renderer → overlay (forwarded by main): push the latest pet state.
    pushState: payload => ipcRenderer.send('robo:pet-overlay:state', payload),
    // Overlay → main renderer (forwarded by main): pop back in / composer submit.
    control: payload => ipcRenderer.send('robo:pet-overlay:control', payload),
    // Overlay subscribes to state pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('robo:pet-overlay:state', listener)

      return () => ipcRenderer.removeListener('robo:pet-overlay:state', listener)
    },
    // Main renderer subscribes to overlay control messages.
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('robo:pet-overlay:control', listener)

      return () => ipcRenderer.removeListener('robo:pet-overlay:control', listener)
    }
  },
  // Quick Entry: the global-hotkey mini composer window. Main owns the OS
  // shortcut + the persisted preference; the quick window only captures text
  // and hands it back, and the primary renderer submits it through the normal
  // prompt path.
  quickEntry: {
    getSettings: () => ipcRenderer.invoke('robo:quick-entry:settings:get'),
    setSettings: patch => ipcRenderer.invoke('robo:quick-entry:settings:set', patch),
    submit: payload => ipcRenderer.send('robo:quick-entry:submit', payload),
    dismiss: () => ipcRenderer.send('robo:quick-entry:dismiss'),
    // Primary renderer → main → quick window: gateway connection state + the
    // recent-session options the target picker offers. Main caches the latest
    // payload so a freshly spawned quick window starts from truth.
    pushState: payload => ipcRenderer.send('robo:quick-entry:state', payload),
    // Quick window subscribes to those pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('robo:quick-entry:state', listener)

      return () => ipcRenderer.removeListener('robo:quick-entry:state', listener)
    },
    // Main → primary renderer: a submit captured by the quick window.
    onSubmit: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('robo:quick-entry:submit', listener)

      return () => ipcRenderer.removeListener('robo:quick-entry:submit', listener)
    },
    // Main → quick window: you were just summoned (reset draft + refocus).
    onShown: callback => {
      const listener = () => callback()
      ipcRenderer.on('robo:quick-entry:shown', listener)

      return () => ipcRenderer.removeListener('robo:quick-entry:shown', listener)
    }
  },
  getBootProgress: () => ipcRenderer.invoke('robo:boot-progress:get'),
  getConnectionConfig: profile => ipcRenderer.invoke('robo:connection-config:get', profile),
  saveConnectionConfig: payload => ipcRenderer.invoke('robo:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('robo:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('robo:connection-config:test', payload),
  sshConfigHosts: () => ipcRenderer.invoke('robo:ssh-config:hosts'),
  sshResolveHost: host => ipcRenderer.invoke('robo:ssh-config:resolve', host),
  probeConnectionConfig: remoteUrl => ipcRenderer.invoke('robo:connection-config:probe', remoteUrl),
  oauthLoginConnectionConfig: remoteUrl => ipcRenderer.invoke('robo:connection-config:oauth-login', remoteUrl),
  oauthLogoutConnectionConfig: remoteUrl => ipcRenderer.invoke('robo:connection-config:oauth-logout', remoteUrl),
  profile: {
    get: () => ipcRenderer.invoke('robo:profile:get'),
    set: name => ipcRenderer.invoke('robo:profile:set', name)
  },
  api: request => ipcRenderer.invoke('robo:api', request),
  notify: payload => ipcRenderer.invoke('robo:notify', payload),
  requestMicrophoneAccess: () => ipcRenderer.invoke('robo:requestMicrophoneAccess'),
  readFileDataUrl: filePath => ipcRenderer.invoke('robo:readFileDataUrl', filePath),
  readFileDataUrlForAttach: filePath => ipcRenderer.invoke('robo:readFileDataUrlForAttach', filePath),
  dataUrlReadMax: {
    get: () => ipcRenderer.invoke('robo:data-url-read-max:get'),
    set: maxMb => ipcRenderer.invoke('robo:data-url-read-max:set', maxMb)
  },
  readFileText: filePath => ipcRenderer.invoke('robo:readFileText', filePath),
  selectPaths: options => ipcRenderer.invoke('robo:selectPaths', options),
  selectSavePath: options => ipcRenderer.invoke('robo:selectSavePath', options),
  writeClipboard: text => ipcRenderer.invoke('robo:writeClipboard', text),
  readClipboard: () => ipcRenderer.invoke('robo:readClipboard'),
  saveImageFromUrl: url => ipcRenderer.invoke('robo:saveImageFromUrl', url),
  saveImageBuffer: (data, ext) => ipcRenderer.invoke('robo:saveImageBuffer', { data, ext }),
  saveClipboardImage: () => ipcRenderer.invoke('robo:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('robo:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('robo:watchPreviewFile', url),
  watchDirectory: dir => ipcRenderer.invoke('robo:watchDirectory', dir),
  stopPreviewFileWatch: id => ipcRenderer.invoke('robo:stopPreviewFileWatch', id),
  setActiveWork: payload => ipcRenderer.send('robo:active-work', payload),
  setTitleBarTheme: payload => ipcRenderer.send('robo:titlebar-theme', payload),
  setNativeTheme: mode => ipcRenderer.send('robo:native-theme', mode),
  setTranslucency: payload => ipcRenderer.send('robo:translucency', payload),
  setKeepAwake: on => ipcRenderer.send('robo:keep-awake', on),
  setPreviewShortcutActive: active => ipcRenderer.send('robo:previewShortcutActive', Boolean(active)),
  openExternal: url => ipcRenderer.invoke('robo:openExternal', url),
  openPreviewInBrowser: url => ipcRenderer.invoke('robo:openPreviewInBrowser', url),
  fetchLinkTitle: url => ipcRenderer.invoke('robo:fetchLinkTitle', url),
  sanitizeWorkspaceCwd: cwd => ipcRenderer.invoke('robo:workspace:sanitize', cwd),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('robo:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('robo:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('robo:setting:defaultProjectDir:pick')
  },
  zoom: {
    // Current zoom of this window, as { level, percent }.
    get: () => ipcRenderer.invoke('robo:zoom:get'),
    setPercent: percent => ipcRenderer.send('robo:zoom:set-percent', percent),
    // Fires on every zoom change, including the Ctrl/Cmd +/-/0 shortcuts,
    // so the settings UI can stay in sync with the keyboard.
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('robo:zoom:changed', listener)

      return () => ipcRenderer.removeListener('robo:zoom:changed', listener)
    }
  },
  revealLogs: () => ipcRenderer.invoke('robo:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('robo:logs:recent'),
  readDir: dirPath => ipcRenderer.invoke('robo:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('robo:fs:gitRoot', startPath),
  revealPath: targetPath => ipcRenderer.invoke('robo:fs:reveal', targetPath),
  openDir: dirPath => ipcRenderer.invoke('robo:fs:openDir', dirPath),
  desktopPluginsRoot: () => ipcRenderer.invoke('robo:fs:desktopPluginsRoot'),
  renamePath: (targetPath, newName) => ipcRenderer.invoke('robo:fs:rename', targetPath, newName),
  writeTextFile: (filePath, content) => ipcRenderer.invoke('robo:fs:writeText', filePath, content),
  trashPath: targetPath => ipcRenderer.invoke('robo:fs:trash', targetPath),
  git: {
    worktreeList: repoPath => ipcRenderer.invoke('robo:git:worktreeList', repoPath),
    worktreeAdd: (repoPath, options) => ipcRenderer.invoke('robo:git:worktreeAdd', repoPath, options),
    worktreeRemove: (repoPath, worktreePath, options) =>
      ipcRenderer.invoke('robo:git:worktreeRemove', repoPath, worktreePath, options),
    branchSwitch: (repoPath, branch) => ipcRenderer.invoke('robo:git:branchSwitch', repoPath, branch),
    branchList: repoPath => ipcRenderer.invoke('robo:git:branchList', repoPath),
    baseBranchList: repoPath => ipcRenderer.invoke('robo:git:baseBranchList', repoPath),
    repoStatus: repoPath => ipcRenderer.invoke('robo:git:repoStatus', repoPath),
    fileDiff: (repoPath, filePath) => ipcRenderer.invoke('robo:git:fileDiff', repoPath, filePath),
    scanRepos: (roots, options) => ipcRenderer.invoke('robo:git:scanRepos', roots, options),
    review: {
      list: (repoPath, scope, baseRef) => ipcRenderer.invoke('robo:git:review:list', repoPath, scope, baseRef),
      diff: (repoPath, filePath, scope, baseRef, staged) =>
        ipcRenderer.invoke('robo:git:review:diff', repoPath, filePath, scope, baseRef, staged),
      stage: (repoPath, filePath) => ipcRenderer.invoke('robo:git:review:stage', repoPath, filePath),
      unstage: (repoPath, filePath) => ipcRenderer.invoke('robo:git:review:unstage', repoPath, filePath),
      revert: (repoPath, filePath) => ipcRenderer.invoke('robo:git:review:revert', repoPath, filePath),
      revParse: (repoPath, ref) => ipcRenderer.invoke('robo:git:review:revParse', repoPath, ref),
      commit: (repoPath, message, push) => ipcRenderer.invoke('robo:git:review:commit', repoPath, message, push),
      commitContext: repoPath => ipcRenderer.invoke('robo:git:review:commitContext', repoPath),
      push: repoPath => ipcRenderer.invoke('robo:git:review:push', repoPath),
      shipInfo: repoPath => ipcRenderer.invoke('robo:git:review:shipInfo', repoPath),
      createPr: repoPath => ipcRenderer.invoke('robo:git:review:createPr', repoPath)
    }
  },
  terminal: {
    cwd: id => ipcRenderer.invoke('robo:terminal:cwd', id),
    dispose: id => ipcRenderer.invoke('robo:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('robo:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('robo:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('robo:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `robo:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `robo:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('robo:close-preview-requested', listener)

    return () => ipcRenderer.removeListener('robo:close-preview-requested', listener)
  },
  onOpenFolderRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('robo:open-folder-requested', listener)

    return () => ipcRenderer.removeListener('robo:open-folder-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('robo:open-updates', listener)

    return () => ipcRenderer.removeListener('robo:open-updates', listener)
  },
  onDeepLink: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('robo:deep-link', listener)

    return () => ipcRenderer.removeListener('robo:deep-link', listener)
  },
  signalDeepLinkReady: () => ipcRenderer.invoke('robo:deep-link-ready'),
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('robo:window-state-changed', listener)

    return () => ipcRenderer.removeListener('robo:window-state-changed', listener)
  },
  onFocusSession: callback => {
    const listener = (_event, sessionId) => callback(sessionId)
    ipcRenderer.on('robo:focus-session', listener)

    return () => ipcRenderer.removeListener('robo:focus-session', listener)
  },
  onNotificationAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('robo:notification-action', listener)

    return () => ipcRenderer.removeListener('robo:notification-action', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('robo:preview-file-changed', listener)

    return () => ipcRenderer.removeListener('robo:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('robo:backend-exit', listener)

    return () => ipcRenderer.removeListener('robo:backend-exit', listener)
  },
  // Soft gateway-mode apply finished tearing down the primary backend. Renderer
  // should wipe session lists + re-dial without a window reload.
  onConnectionApplied: callback => {
    const listener = () => callback()
    ipcRenderer.on('robo:connection:applied', listener)

    return () => ipcRenderer.removeListener('robo:connection:applied', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('robo:power-resume', listener)

    return () => ipcRenderer.removeListener('robo:power-resume', listener)
  },
  // AC ↔ battery transitions; renderers slow their backstop polls on battery.
  getOnBattery: () => ipcRenderer.invoke('robo:power-battery:get'),
  onBatteryChanged: callback => {
    const listener = (_event, onBattery) => callback(Boolean(onBattery))
    ipcRenderer.on('robo:power-battery', listener)

    return () => ipcRenderer.removeListener('robo:power-battery', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('robo:boot-progress', listener)

    return () => ipcRenderer.removeListener('robo:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.ts (apps/desktop/electron/bootstrap-runner.ts).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('robo:bootstrap:get'),
  continueBootstrapLocal: () => ipcRenderer.invoke('robo:bootstrap:continue-local'),
  resetBootstrap: () => ipcRenderer.invoke('robo:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('robo:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('robo:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('robo:bootstrap:event', listener)

    return () => ipcRenderer.removeListener('robo:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('robo:version'),
  getRemoteDisplayReason: () => ipcRenderer.invoke('robo:get-remote-display-reason'),
  uninstall: {
    summary: () => ipcRenderer.invoke('robo:uninstall:summary'),
    run: mode => ipcRenderer.invoke('robo:uninstall:run', { mode })
  },
  updates: {
    check: () => ipcRenderer.invoke('robo:updates:check'),
    apply: opts => ipcRenderer.invoke('robo:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('robo:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('robo:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('robo:updates:progress', listener)

      return () => ipcRenderer.removeListener('robo:updates:progress', listener)
    }
  },
  themes: {
    fetchMarketplace: id => ipcRenderer.invoke('robo:vscode-theme:fetch', id),
    searchMarketplace: query => ipcRenderer.invoke('robo:vscode-theme:search', query)
  },
  // Find-in-page (Ctrl/Cmd+F): delegates to Electron's
  // webContents.findInPage on the IPC sender's window so a Cmd+F pressed
  // in a secondary session window searches THAT window, not the primary.
  // `onFoundInPage` returns the unsubscribe fn; the renderer wires it via
  // `initFindInPageListener` in store/find-in-page.ts and tears it down
  // when the FindBar unmounts.
  findInPage: (query, options) => ipcRenderer.invoke('robo:find-in-page', query, options),
  stopFindInPage: () => ipcRenderer.invoke('robo:stop-find-in-page'),
  onFoundInPage: callback => {
    const listener = (_event, result) => callback(result)
    ipcRenderer.on('robo:found-in-page', listener)

    return () => ipcRenderer.removeListener('robo:found-in-page', listener)
  }
})
