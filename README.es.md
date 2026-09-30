<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/robo-lockup-dark.svg">
  <img src="assets/brand/robo-lockup-light.svg" alt="Robo by Ignitee Now" width="420">
</picture>

# Tu IA que de verdad hace el trabajo.

Dale una tarea a Robo en tu escritorio y revísala desde tu teléfono.<br>
Funciona en tu propio ordenador, usa herramientas reales y pregunta antes de hacer algo arriesgado.

![Windows · macOS · Linux](https://img.shields.io/badge/Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-0E1437?style=for-the-badge)
![Terminal · Escritorio · Navegador · Voz · API](https://img.shields.io/badge/Terminal%20%C2%B7%20Escritorio%20%C2%B7%20Navegador%20%C2%B7%20Voz%20%C2%B7%20API-3F3E98?style=for-the-badge)

[Instalar](#instalar) · [Ejecutarlo](#ejecutarlo) · [Úsalo desde cualquier lugar](#úsalo-desde-cualquier-lugar) · [Qué puede hacer](#qué-puede-hacer)

[English](README.md) · **Español** · [中文](README.zh-CN.md) · [اردو](README.ur-pk.md)

</div>

---

## Encárgale cualquier cosa

| Día a día | Técnico |
|---|---|
| "Ordena mi carpeta de Descargas por tipo." | "La compilación falla. Averigua por qué y arréglalo." |
| "Convierte estas notas de reunión en una lista de tareas con responsables y fechas." | "Revisa este log de 2 GB y dime qué se rompió anoche." |
| "Cada mañana a las 8, mándame las noticias de tecnología por Telegram." | "Abre este .exe y dime con qué servidores se comunica." |
| "Compara estas dos hojas de cálculo y dime quién falta en la nueva." | "Investiga las tres mejores opciones para X, compáralas y dame las fuentes." |

Robo planifica la tarea, la hace con herramientas reales (terminal, archivos, navegador, código), comprueba
su propio trabajo y pregunta **Permitir una vez / Permitir en esta sesión / Denegar** antes de algo arriesgado.
*Permitir en esta sesión* deja de preguntar hasta que esa sesión termina; los comandos de la lista de bloqueo de
Robo siguen bloqueados.
Funciona con el modelo que elijas: OpenAI, Anthropic, Gemini, DeepSeek, Kimi, OpenRouter,
o un modelo local con Ollama o cualquier servidor compatible con OpenAI.

## Instalar

**Windows (PowerShell)**

```powershell
git clone https://github.com/igniteenow/robo
cd robo
Set-ExecutionPolicy -Scope Process Bypass -Force
.\install-robo.ps1
```

**macOS · Linux · WSL**

```bash
git clone https://github.com/igniteenow/robo
cd robo
bash install-robo.sh
```

Después **abre una terminal nueva** y elige tu modelo. En Windows el instalador añade `robo` a tu PATH;
en macOS y Linux te indica la línea que debes añadir si `~/.local/bin` aún no está en tu PATH.

```bash
robo model        # elige un proveedor y pega su clave de API
robo              # empieza a chatear
```

Necesitas `git` y Python 3.11, 3.12 o 3.13 (3.14 aún no es compatible). El instalador prepara Node
por sí mismo y nunca sobrescribe tu configuración, memoria ni habilidades. En Debian/Ubuntu, la voz necesita además `sudo apt install libportaudio2`.
Si algo no va bien, ejecuta `robo doctor`. Para instalaciones automatizadas, llama directamente a
`scripts/install.sh` o `scripts/install.ps1`.

## Ejecutarlo

Todas las formas de usar Robo comparten las mismas sesiones, memoria y configuración.

| Quieres | Ejecuta | Obtienes |
|---|---|---|
| **Terminal** | `robo` | App de terminal con chat de voz |
| **App de escritorio** | `robo desktop` | App nativa para Windows, macOS y Linux. La primera vez la compila; luego abre al instante |
| **Navegador** | `robo dashboard` | Robo en `http://localhost:9119`: chat, ajustes, sesiones, habilidades, MCP |
| **Una respuesta rápida** | `robo -z "Resume README.md"` | Una pregunta, una respuesta, sin interfaz |
| **Tus propias apps** | `robo gateway` | API compatible con OpenAI en `http://localhost:8642/v1`, cuando `API_SERVER_KEY` está configurada ([detalles](#api-http)) |

### Voz

Habla con Robo en la terminal y en la app de escritorio. La transcripción se hace en tu equipo.

| Comando | Qué hace |
|---|---|
| `/voice on` | Chat de voz manos libres. Las respuestas se oyen y se ven en pantalla, con enlaces y detalles completos |
| `/wake on` | Di **"Hey Roh Boh"** para empezar a hablar sin tocar el teclado |

### App de escritorio

- **Servidores MCP en Settings → MCP.** Añade, busca y cambia servidores Model Context Protocol sin editar archivos.
- **Se actualiza sola.** Cuando haya una versión nueva, pulsa **Update now**. Robo se cierra, muestra el progreso y se vuelve a abrir al terminar.
- **Conéctate a un Robo en otra máquina:** Settings → Gateway → Remote gateway.

## Úsalo desde cualquier lugar

Ejecuta Robo en tu PC o en un servidor y usa **la misma terminal de Robo** desde cualquier navegador: teléfono, tableta o portátil.

```bash
robo dashboard --host 0.0.0.0 --no-open
```

La primera vez, Robo te pide crear un **usuario y contraseña**. Nunca sirve una dirección
de red sin inicio de sesión. Después abre `http://<IP-de-este-equipo>:9119` en tu otro dispositivo.

- **Windows:** permite el puerto una vez, en PowerShell *como administrador*:
  `New-NetFirewallRule -DisplayName "Robo 9119" -Direction Inbound -Protocol TCP -LocalPort 9119 -Action Allow -Profile Private`
- **Fuera de tu red de casa:** usa una VPN como Tailscale. No abras el puerto en tu router.
- **Detenerlo:** `robo dashboard --stop`

También puedes escribirle a Robo desde **Telegram, WhatsApp, Discord, Slack** y más: ejecuta `robo gateway setup`.

## Qué puede hacer

- **Trabaja con tus documentos.** Adjunta logs, notas, código, CSV, JSON, HTML o PowerPoint de cualquier tamaño (`/attach <archivo>`). Robo los indexa en tu equipo y responde con los pasajes exactos.
- **Hace trabajo real.** Programación, depuración, investigación, redacción, datos, limpieza de archivos y administración de sistemas, con una terminal real, edición de archivos, un navegador real y ejecución de código.
- **Mira dentro del software de forma segura.** Análisis estático de programas con Ghidra, radare2 o rizin si están instalados, o con un analizador integrado si no. El archivo nunca se ejecuta.
- **Mejora con el uso.** Guarda lo que funciona como habilidades reutilizables, mantiene memoria a largo plazo, busca en conversaciones pasadas y aprende cómo te gusta hacer las cosas.
- **Trabaja mientras tú no.** Tareas programadas ("cada mañana a las 8…") y subagentes en paralelo.
- **Mantiene limpio tu equipo.** Los trabajos pesados o arriesgados pueden ejecutarse en Docker, por SSH o en un sandbox en la nube (Modal, Daytona).

## Comandos del día a día

| Comando | Qué hace |
|---|---|
| `robo model` | Cambiar de modelo o proveedor |
| `robo update` | Actualizar Robo (o **Update now** en la app de escritorio) |
| `robo doctor` | Revisar tu instalación |
| `/help` | Todos los comandos dentro de un chat |
| `/edit` | Recuperar tu último mensaje y reescribirlo |

Mientras Robo trabaja, simplemente escribe: Robo lee tu mensaje al momento y cambia de rumbo (el paso que
estaba ejecutando se detiene). `/busy steer` deja terminar primero el paso actual; `/busy queue` guarda tu
mensaje para el siguiente turno.

## Hazlo tuyo

Todo son archivos de texto en `~/.robo`, fáciles de editar, respaldar o mover. En Windows la carpeta es
`%USERPROFILE%\.robo` si instalaste con `install-robo.ps1`, y `%LOCALAPPDATA%\robo` si usaste
`scripts/install.ps1`.

| Archivo | Qué contiene |
|---|---|
| `SOUL.md` | La personalidad y reglas de Robo: tono, cuánto cuidado tiene, estilo |
| `memories/USER.md` | Datos sobre ti, para que no tengas que repetirte |
| `memories/MEMORY.md` | Lo que Robo ha aprendido. Se actualiza solo; también puedes decir "recuerda que…" |
| `skills/` | Procedimientos reutilizables. Di "guarda esto como habilidad" |
| `.env` | Tus claves de API |

<details>
<summary><b>API HTTP</b></summary>

<a id="api-http"></a>
Usa Robo desde tus propias apps o interfaces de chat como Open WebUI. La API solo arranca cuando añades una
clave de al menos 16 caracteres a `.env` en tu carpeta de Robo (ver [Hazlo tuyo](#hazlo-tuyo)):

```bash
API_SERVER_KEY=your-secret-key-16-plus-chars
```

```bash
robo gateway
curl http://localhost:8642/v1/chat/completions \
  -H "Authorization: Bearer your-secret-key-16-plus-chars" \
  -H "Content-Type: application/json" \
  -d '{"model": "robo-engineer", "messages": [{"role": "user", "content": "Hello!"}]}'
```

La API también necesita el paquete `aiohttp`, que `install-robo.ps1` e `install-robo.sh` no instalan.
Si falta, `robo gateway` lo indica y muestra el comando que lo instala.

</details>

<details>
<summary><b>Docker (Linux)</b></summary>

```bash
ROBO_UID=$(id -u) ROBO_GID=$(id -g) docker compose up -d
```

Ejecuta el gateway y el dashboard en `http://localhost:9119`, con tus datos en `~/.robo`.
El archivo compose usa la red del host, que Docker ofrece en Linux. En macOS, actívala antes en
Docker Desktop 4.34 o posterior: inicia sesión y ve a **Settings → Resources → Network → Enable host networking**.

</details>

## Acceso anticipado

Robo 3.0.1 está en acceso anticipado. Pruébalo y dinos qué te parece:
[abre un issue](https://github.com/igniteenow/robo/issues) o escribe a
[support@igniteenow.com](mailto:support@igniteenow.com). La voz y la GPU dependen de tu
hardware; `robo doctor` muestra lo que está disponible.

## Licencia

[MIT](LICENSE) · Creado por [Ignitee Now](https://igniteenow.com).

<sub>Basado en [Hermes Agent](https://github.com/NousResearch/hermes-agent) de Nous Research, con licencia MIT. Ver [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).</sub>
