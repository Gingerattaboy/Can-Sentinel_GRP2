## Virtual CAN network (vcan0): setup and test

### Requirements

- Ubuntu 22.04 or 24.04 on a **real virtual machine (VirtualBox, VMware) or a native install**
- Packages:

```bash
sudo apt update
sudo apt install -y can-utils git build-essential python3-pip
```

### Set up vcan0

From the repo root:

```bash
./scripts/setup_vcan.sh
```

The script loads the `vcan` kernel module, creates `vcan0` if it does not exist and brings it up.
It is safe to run more than once. To use another name: `./scripts/setup_vcan.sh vcan1`.

If the script is not executable, run `chmod +x scripts/*.sh` once, or start it with `bash scripts/setup_vcan.sh`.

### Test the network with candump and cansend

Open two terminals.

**Terminal 1 (listen):**

```bash
candump vcan0
```

**Terminal 2 (send):**

```bash
cansend vcan0 123#DEADBEEF
cansend vcan0 100#0BB8010000000000
```

Terminal 1 should print one line per frame, for example:

```
  vcan0  123   [4]  DE AD BE EF
  vcan0  100   [8]  0B B8 01 00 00 00 00 00
```

If both frames appear, `vcan0` works. Stop `candump` with `Ctrl + C`.

Optional load test (about 100 frames per second on ID 0x100, stop with `Ctrl + C`):

```bash
cangen vcan0 -I 100 -g 10 -L 8 -D r
```

### Verified on

| Environment | Ubuntu version | vcan0 works? | Tested by | Date |
|-------------|----------------|--------------|-----------|------|
| VirtualBox VM | (fill in: `lsb_release -d`) | (yes / no) | Abdul Wahid | (date) |
| (teammate's machine) | | | | |

Kernel for reference: run `uname -r` and add it above if something fails.

### Troubleshooting

| Problem | Fix |
|---------|-----|
| `candump: command not found` | `sudo apt install -y can-utils` |
| `Cannot find device "vcan0"` | Run `./scripts/setup_vcan.sh` first |
| `modprobe: FATAL: Module vcan not found` | `sudo apt install -y linux-modules-extra-$(uname -r)`, then run the setup script again. If it still fails, switch to a VirtualBox VM |
| `socket: Address family not supported by protocol` | The kernel has no CAN support. Use an Ubuntu VM (see the WSL note below) |
| `Permission denied` on a script | `chmod +x scripts/*.sh` |
| Nothing shows in `candump` | Check that both commands use `vcan0` and that `candump` was started before you sent |

### WSL caveat (read this if you use Windows)

**Do not use WSL for this project.** `vcan` is a Linux kernel module, and the default WSL2 kernel does not
include CAN support, so `sudo modprobe vcan` typically fails with `Module vcan not found`, and
`candump` fails with `Address family not supported by protocol`. The original WSL (WSL1) has no real
kernel at all, so it cannot work either.

It is possible to make WSL2 work by building a custom WSL2 kernel with `CONFIG_CAN` and
`CONFIG_CAN_VCAN` enabled and pointing `.wslconfig` at it, but this takes a long build, can break
other tools such as Docker Desktop, and is not supported by the team. **Use an Ubuntu VM instead.**

Quick check on any machine:

```bash
sudo modprobe vcan && echo "vcan available" || echo "vcan NOT available: use an Ubuntu VM"
```

Also not suitable: Google Cloud Shell, Colab and GitHub Codespaces. They are containers that share the
host kernel, so `modprobe vcan` usually fails there too. A cloud VM (for example Compute Engine) may
work but sometimes needs `linux-modules-extra-$(uname -r)` installed first.

Recommended setup for Windows users: VirtualBox with an Ubuntu 22.04 or 24.04 VM
(2 CPUs, 4 GB RAM, 30 GB disk).
