# SAN-90 dependency installation

This guide prepares a fresh Ubuntu 24.04 x86-64 machine for the SAN-90
backend, React frontend, and managed USB handoff. The external AI detector is
optional and uses a separate Python environment.

## 1. Install host packages

```bash
sudo apt update
sudo apt install \
  build-essential curl git libusb-1.0-0 python3 python3-pip \
  usbutils wget xz-utils
```

Ubuntu 24.04 supplies Node.js 18, which is too old for this project. The
frontend requires Node.js 20.19 or newer.

## 2. Install a current Node.js LTS release

The following installs the checksum-verified Node.js 24.18.0 LTS binary under
the current user's `~/.local` directory:

```bash
node_version=v24.18.0
node_archive="node-${node_version}-linux-x64.tar.xz"
node_url="https://nodejs.org/dist/${node_version}"
node_tmp_dir="$(mktemp -d)"
user_data_dir="$(getent passwd "$(id -u)" | cut -d: -f6)"

wget -q "${node_url}/${node_archive}" -O "${node_tmp_dir}/${node_archive}"
wget -q "${node_url}/SHASUMS256.txt" -O "${node_tmp_dir}/SHASUMS256.txt"
(
  cd "${node_tmp_dir}"
  grep " ${node_archive}$" SHASUMS256.txt | sha256sum -c -
)

mkdir -p "${user_data_dir}/.local/opt" "${user_data_dir}/.local/bin"
tar -xJf "${node_tmp_dir}/${node_archive}" -C "${user_data_dir}/.local/opt"
ln -sfn \
  "${user_data_dir}/.local/opt/node-${node_version}-linux-x64/bin/node" \
  "${user_data_dir}/.local/bin/node"
ln -sfn \
  "${user_data_dir}/.local/opt/node-${node_version}-linux-x64/bin/npm" \
  "${user_data_dir}/.local/bin/npm"
ln -sfn \
  "${user_data_dir}/.local/opt/node-${node_version}-linux-x64/bin/npx" \
  "${user_data_dir}/.local/bin/npx"

export PATH="${user_data_dir}/.local/bin:${PATH}"
node --version
npm --version
```

Ubuntu's default `~/.profile` adds `~/.local/bin` to `PATH` when that directory
exists. Open a new login shell after installation if `command -v node` still
selects `/usr/bin/node`.

## 3. Install the backend and frontend dependencies

From the repository root:

```bash
cd /home/tuancoi/san90

python3 -m pip install --user --break-system-packages \
  -r backend/requirements.txt

npm ci
```

`--user` keeps the Python packages under the current user account.
`--break-system-packages` is needed for Ubuntu 24.04's externally managed
Python policy; this command does not replace the distribution's Python
packages.

## 4. Install the HAROGIC machine configuration

The HTRA SDK requires both its USB permission rule and its device database.
Installing only the udev rule causes `Device_List` to report zero devices.

```bash
cd /home/tuancoi/san90

sudo install -o root -g root -m 0644 \
  harogic/Linux_API/htraapi/configs/htra-cyusb.rules \
  /etc/udev/rules.d/htra-cyusb.rules

sudo install -o root -g root -m 0644 \
  harogic/Linux_API/htraapi/configs/htrausb.conf \
  /etc/htrausb.conf

sudo udevadm control --reload-rules
sudo udevadm trigger \
  --subsystem-match=usb --attr-match=idVendor=367f --action=add
udevadm settle
```

Verify that the analyzer is visible and its device node is writable:

```bash
lsusb -d 367f:0001
usb_line="$(lsusb -d 367f:0001)"
usb_bus="$(printf '%s\n' "${usb_line}" | awk '{print $2}')"
usb_device="$(printf '%s\n' "${usb_line}" | awk '{gsub(":", "", $4); print $4}')"
stat -c '%A %a %U:%G %n' "/dev/bus/usb/${usb_bus}/${usb_device}"
```

The expected node mode is `666` (`crw-rw-rw-`) with the supplied vendor rule.

## 5. Install `usbreset`

The managed SAN-90 start/stop workflow requires `usbreset`. Ubuntu 24.04's
`usbutils` package does not include that executable, so build the small
upstream usbutils implementation:

```bash
usbutils_commit=8fb7ed457876db9770ef0c4067155866faffcca9
usbreset_tmp_dir="$(mktemp -d)"
user_data_dir="$(getent passwd "$(id -u)" | cut -d: -f6)"

wget -q \
  "https://raw.githubusercontent.com/gregkh/usbutils/${usbutils_commit}/usbreset.c" \
  -O "${usbreset_tmp_dir}/usbreset.c"
gcc -O2 -Wall -Wextra \
  -o "${usbreset_tmp_dir}/usbreset" "${usbreset_tmp_dir}/usbreset.c"
install -m 0755 \
  "${usbreset_tmp_dir}/usbreset" "${user_data_dir}/.local/bin/usbreset"

export PATH="${user_data_dir}/.local/bin:${PATH}"
command -v usbreset
```

Running `usbreset` without an argument lists devices without resetting them.
Do not reset the SAN-90 while the backend or SAStudio owns it.

## 6. Validate the installation

Normal non-hardware validation:

```bash
python3 -m pip check
python3 -c 'import backend.main; print("backend import: OK")'
npm ls --depth=0
npm test
npm run lint
npm run build
```

Simulator smoke test:

```bash
npm run backend:start:simulator
npm run frontend:start
npm run services:status
curl -s http://127.0.0.1:8000/api/analyzer/status
npm run frontend:stop
npm run backend:stop
```

## 7. Start the real SAN-90 application

Fully exit SAStudio before starting the backend. Only one process may own the
analyzer.

```bash
lsusb -d 367f:0001
npm run backend:start
npm run frontend:start
npm run services:status
```

Open:

```text
http://localhost:5173/?source=san90
```

If startup fails, inspect:

```bash
tail -n 100 .run/backend.log
tail -n 100 .run/frontend.log
```

Stop both services cleanly with:

```bash
npm run frontend:stop
npm run backend:stop
```

## Optional FT232H and AI dependencies

The FT232H Python dependency is included in `backend/requirements.txt`, but
physical access also requires the udev setup in
[`ft232h-rf-switch.md`](ft232h-rf-switch.md).

The external detector under `AI services/AI-for-san90` is not required to run
the spectrum console. Install its pinned Torch, Torchvision, OpenCV, and
Ultralytics packages in a dedicated virtual environment, then independently
verify CPU/CUDA compatibility. See [`project-status.md`](project-status.md)
and [`ai-gray8-stream.md`](ai-gray8-stream.md) before enabling it.
