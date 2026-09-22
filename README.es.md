<p align="center">
  <img src="assets/banner.png" alt="Robo Agent" width="100%">
</p>

# Robo Agent ◆
<p align="center">
  <a href="https://github.com/IgniteeNow/robo-engineer/tree/main/website/docs">Robo Agent</a> | <a href="https://github.com/IgniteeNow/robo-engineer/tree/main/website/docs">Robo Desktop</a>
</p>
<p align="center">
  <a href="website/docs/index.mdx"><img src="https://img.shields.io/badge/Docs-in%20this%20repo-EF8A22?style=for-the-badge" alt="Documentación"></a>
  <a href="https://github.com/IgniteeNow/robo-engineer/discussions"><img src="https://img.shields.io/badge/Discussions-181717?style=for-the-badge&logo=github&logoColor=white" alt="Discussions"></a>
  <a href="https://github.com/IgniteeNow/robo-engineer/blob/main/LICENSE"><img src="https://img.shields.io/badge/Licencia-MIT-green?style=for-the-badge" alt="Licencia: MIT"></a>
  <a href="README.md"><img src="https://img.shields.io/badge/Lang-English-blue?style=for-the-badge" alt="English"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Lang-中文-red?style=for-the-badge" alt="中文"></a>
  <a href="README.ur-pk.md"><img src="https://img.shields.io/badge/Lang-اردو-green?style=for-the-badge" alt="اردو"></a>
</p>

**El agente de IA con mejora continua.** Es el único agente con un bucle de aprendizaje integrado: crea habilidades a partir de la experiencia, las mejora durante el uso, se impulsa a sí mismo a persistir el conocimiento, busca en sus propias conversaciones pasadas y construye un modelo cada vez más profundo de quién eres a lo largo de las sesiones. Ejecútalo en un VPS de $5, un clúster de GPUs o infraestructura sin servidor que cuesta casi nada cuando está inactivo. No está atado a tu laptop — habla con él desde Telegram mientras trabaja en una VM en la nube.

Usa cualquier modelo que quieras — [OpenRouter](https://openrouter.ai) (más de 200 modelos), [NovitaAI](https://novita.ai), [NVIDIA NIM](https://build.nvidia.com) (Nemotron), [Xiaomi MiMo](https://platform.xiaomimimo.com), [z.ai/GLM](https://z.ai), [Kimi/Moonshot](https://platform.moonshot.ai), [MiniMax](https://www.minimax.io), [Hugging Face](https://huggingface.co), OpenAI, o tu propio endpoint. Cambia con `robo model` — sin cambios de código, sin dependencias.

<table>
<tr><td><b>Una interfaz de terminal real</b></td><td>TUI completa con edición multilínea, autocompletado de comandos, historial de conversaciones, interrupción y redirección, y salida de herramientas en streaming.</td></tr>
<tr><td><b>Vive donde tú vives</b></td><td>Telegram, Discord, Slack, WhatsApp, Signal y CLI — todo desde un único proceso gateway. Transcripción de notas de voz, continuidad de conversación entre plataformas.</td></tr>
<tr><td><b>Un bucle de aprendizaje cerrado</b></td><td>Memoria curada por el agente con recordatorios periódicos. Creación autónoma de habilidades tras tareas complejas. Las habilidades mejoran solas durante el uso. Búsqueda FTS5 de sesiones con resumención por LLM para recuperación entre sesiones. Modelado de usuario dialéctico <a href="https://github.com/plastic-labs/honcho">Honcho</a>. Compatible con el estándar abierto de <a href="https://agentskills.io">agentskills.io</a>.</td></tr>
<tr><td><b>Automatizaciones programadas</b></td><td>Planificador cron integrado con entrega a cualquier plataforma. Informes diarios, copias de seguridad nocturnas, auditorías semanales — todo en lenguaje natural, ejecutándose de forma autónoma.</td></tr>
<tr><td><b>Delega y paraleliza</b></td><td>Lanza subagentes aislados para flujos de trabajo paralelos. Escribe scripts de Python que llaman a herramientas vía RPC, convirtiendo pipelines de múltiples pasos en turnos de coste cero de contexto.</td></tr>
<tr><td><b>Funciona en cualquier lugar, no solo en tu laptop</b></td><td>Seis backends de terminal — local, Docker, SSH, Singularity, Modal y Daytona. Daytona y Modal ofrecen persistencia sin servidor — el entorno de tu agente hiberna cuando está inactivo y se activa bajo demanda, costando casi nada entre sesiones. Ejecútalo en un VPS de $5 o un clúster de GPUs.</td></tr>
<tr><td><b>Listo para investigación</b></td><td>Generación de trayectorias en lote, compresión de trayectorias para entrenar la próxima generación de modelos de llamadas a herramientas.</td></tr>
</table>

---

## Instalación rápida

### Linux, macOS, WSL2, Termux

```bash
git clone https://github.com/IgniteeNow/robo-engineer.git robo && cd robo && bash install-robo.sh
```

### Windows (nativo, PowerShell)

> **Nota:** En Windows nativo, Robo funciona sin WSL — la CLI, el gateway, la TUI y las herramientas funcionan de forma nativa. Si prefieres usar WSL2, el comando de Linux/macOS de arriba también funciona allí. ¿Encontraste un error? Por favor [crea un issue](https://github.com/IgniteeNow/robo-engineer/issues).

Ejecuta esto en PowerShell:

```powershell
iex (irm https://github.com/IgniteeNow/robo-engineer)
```

El instalador se encarga de todo: uv, Python 3.11, Node.js, ripgrep, ffmpeg, **y un Git Bash portátil** (MinGit, descomprimido en `%LOCALAPPDATA%\robo\git` — no requiere administrador, completamente aislado de cualquier instalación de Git del sistema). Robo usa este Git Bash incluido para ejecutar comandos de shell.

Si ya tienes Git instalado, el instalador lo detecta y lo usa en su lugar. De lo contrario, una descarga de ~45MB de MinGit es todo lo que necesitas — no tocará ni interferirá con ningún Git del sistema.

> **Android / Termux:** La ruta manual probada está documentada en la [guía de Termux](website/docs/getting-started/termux.md). En Termux, Robo instala el extra `.[termux]` curado porque el extra completo `.[all]` actualmente incluye dependencias de voz incompatibles con Android.
>
> **Windows:** Windows nativo es totalmente compatible — el comando de PowerShell de arriba instala todo. Si prefieres usar WSL2, el comando de Linux también funciona allí. La instalación nativa de Windows se encuentra en `%LOCALAPPDATA%\robo`; WSL2 instala en `~/.robo` como en Linux.

Después de la instalación:

```bash
source ~/.bashrc    # recargar shell (o: source ~/.zshrc)
robo              # ¡empieza a chatear!
```

---

## Primeros pasos

```bash
robo              # CLI interactiva — inicia una conversación
robo model        # Elige tu proveedor y modelo LLM
robo tools        # Configura qué herramientas están habilitadas
robo config set   # Establece valores de configuración individuales
robo gateway      # Inicia el gateway de mensajería (Telegram, Discord, etc.)
robo setup        # Ejecuta el asistente de configuración completo
robo update       # Actualiza a la última versión
robo doctor       # Diagnostica cualquier problema
```

📖 **[Documentación completa →](website/docs/index.mdx)**

---


---

## Referencia rápida: CLI vs Mensajería

Robo tiene dos puntos de entrada: inicia la interfaz de terminal con `robo`, o ejecuta el gateway y habla con él desde Telegram, Discord, Slack, WhatsApp, Signal o Email. Una vez en una conversación, muchos comandos de barra son compartidos entre ambas interfaces.

| Acción                              | CLI                                           | Plataformas de mensajería                                                         |
| ----------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------- |
| Empezar a chatear                   | `robo`                                      | Ejecuta `robo gateway setup` + `robo gateway start`, luego envía un mensaje al bot |
| Nueva conversación                  | `/new` o `/reset`                             | `/new` o `/reset`                                                                 |
| Cambiar modelo                      | `/model [proveedor:modelo]`                   | `/model [proveedor:modelo]`                                                       |
| Establecer personalidad             | `/personality [nombre]`                       | `/personality [nombre]`                                                           |
| Reintentar o deshacer último turno  | `/retry`, `/undo`                             | `/retry`, `/undo`                                                                 |
| Comprimir contexto / ver uso        | `/compress`, `/usage`, `/insights [--days N]` | `/compress`, `/usage`, `/insights [days]`                                         |
| Explorar habilidades                | `/skills` o `/<nombre-habilidad>`             | `/<nombre-habilidad>`                                                             |
| Interrumpir trabajo actual          | `Ctrl+C` o enviar un nuevo mensaje            | `/stop` o enviar un nuevo mensaje                                                 |
| Estado específico de plataforma     | `/platforms`                                  | `/status`, `/sethome`                                                             |

Para las listas de comandos completas, consulta la [guía de CLI](website/docs/user-guide/cli.md) y la [guía del Gateway de Mensajería](website/docs/user-guide/messaging/index.md).

---

## Documentación

Toda la documentación está en **[website/docs](website/docs/index.mdx)**:

| Sección                                                                                             | Contenido                                                    |
| --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| [Inicio rápido](website/docs/getting-started/quickstart.md)              | Instalar → configurar → primera conversación en 2 minutos   |
| [Uso de CLI](website/docs/user-guide/cli.md)                             | Comandos, atajos de teclado, personalidades, sesiones        |
| [Configuración](website/docs/user-guide/configuration.md)               | Archivo de configuración, proveedores, modelos, todas las opciones |
| [Gateway de Mensajería](website/docs/user-guide/messaging/index.md)           | Telegram, Discord, Slack, WhatsApp, Signal, Home Assistant   |
| [Seguridad](website/docs/user-guide/security.md)                        | Aprobación de comandos, emparejamiento por DM, aislamiento en contenedor |
| [Herramientas y Toolsets](website/docs/user-guide/features/tools.md)   | Más de 40 herramientas, sistema de toolsets, backends de terminal |
| [Sistema de Habilidades](website/docs/user-guide/features/skills.md)   | Memoria procedimental, Skills Hub, creación de habilidades   |
| [Memoria](website/docs/user-guide/features/memory.md)                   | Memoria persistente, perfiles de usuario, mejores prácticas  |
| [Integración MCP](website/docs/user-guide/features/mcp.md)              | Conecta cualquier servidor MCP para capacidades extendidas   |
| [Programación Cron](website/docs/user-guide/features/cron.md)           | Tareas programadas con entrega a plataforma                  |
| [Archivos de Contexto](website/docs/user-guide/features/context-files.md) | Contexto de proyecto que da forma a cada conversación      |
| [Arquitectura](website/docs/developer-guide/architecture.md)            | Estructura del proyecto, bucle del agente, clases principales |
| [Contribuir](website/docs/developer-guide/contributing.md)              | Configuración de desarrollo, proceso de PR, estilo de código |
| [Referencia de CLI](website/docs/reference/cli-commands.md)             | Todos los comandos y flags                                   |
| [Variables de Entorno](website/docs/reference/environment-variables.md) | Referencia completa de variables de entorno                  |

## Contribuir

¡Las contribuciones son bienvenidas! Consulta la [Guía de Contribución](CONTRIBUTING.es.md) para la configuración del desarrollo, el estilo de código y el proceso de PR.

Inicio rápido para colaboradores — clona y comienza con `setup-robo.sh`:

```bash
git clone https://github.com/IgniteeNow/robo-engineer.git
cd robo-engineer
./setup-robo.sh     # instala uv, crea venv, instala .[all], enlaza ~/.local/bin/robo
./robo              # detecta automáticamente el venv, no necesitas hacer `source` primero
```

Ruta manual (equivalente a lo anterior):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh
```

---

## Comunidad

- 💬 [Discord](https://github.com/IgniteeNow/robo-engineer/discussions)
- 📚 [Skills Hub](https://agentskills.io)
- 🐛 [Issues](https://github.com/IgniteeNow/robo-engineer/issues)
- 🔌 [computer-use-linux](https://github.com/avifenesh/computer-use-linux) — Servidor MCP de control de escritorio Linux para Robo y otros hosts MCP, con árboles de accesibilidad AT-SPI, entrada Wayland/X11, capturas de pantalla y targeting de ventanas del compositor.

---

## Licencia

MIT — ver [LICENSE](LICENSE).

Open source.
