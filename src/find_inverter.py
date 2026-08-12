import socket
import ipaddress

def scan_for_inverter(subnet="192.168.1.0/24", port=8899, timeout=0.3):
    inverter_ips = []
    net = ipaddress.ip_network(subnet, strict=False)

    print(f"Scanning {subnet} for GivEnergy inverter on port {port}...")

    for ip in net.hosts():
        ip = str(ip)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            result = sock.connect_ex((ip, port))
            if result == 0:
                print(f"Possible inverter found at {ip}")
                inverter_ips.append(ip)
        except Exception:
            pass
        finally:
            sock.close()

    return inverter_ips


if __name__ == "__main__":
    ips = scan_for_inverter("192.168.1.0/24")
    if ips:
        print("\nGivEnergy inverter(s) detected:")
        for ip in ips:
            print(f" - {ip}")
    else:
        print("\nNo inverter found.")
