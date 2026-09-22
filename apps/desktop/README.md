# Robo Desktop

Robo Desktop is the graphical control surface for the Robo autonomous
engineering runtime. It provides persistent conversations, tool progress,
approval prompts, voice controls, the animated Robo face, settings, and local
runtime management.

Build it from the repository root:

```powershell
npm run build --workspace apps/desktop
```

Robo updates are installed from a signed or checksum-verified Robo release
package. The desktop does not silently switch to an unrelated runtime.
