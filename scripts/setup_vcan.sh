set -euo pipefail

IFACE="${1:-vcan0}"

echo "Loading vcan kernel module..."
if ! sudo modprobe vcan; then
    echo "ERROR: could not load the vcan module."
    echo "Try: sudo apt install -y linux-modules-extra-$(uname -r)"
    echo "On WSL2 the module is often missing. Use an Ubuntu VM instead."
    exit 1
fi

if ip link show "$IFACE" > /dev/null 2>&1; then
    echo "$IFACE already exists."
else
    echo "Creating $IFACE..."
    sudo ip link add dev "$IFACE" type vcan
fi

sudo ip link set up "$IFACE"

echo "$IFACE is up:"
ip -details link show "$IFACE"
