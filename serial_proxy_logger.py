#!/usr/bin/env python3
# serial_proxy_logger.py
# Simple bidirectional serial proxy with hex logging.
# Usage: python serial_proxy_logger.py --phys COM4 --virt COM7 --log serial.log

import argparse, threading, time, sys, os
import serial

def hexdump(b: bytes) -> str:
    return ' '.join(f"{x:02x}" for x in b)

def forward(src: serial.Serial, dst: serial.Serial, label: str, logf):
    try:
        while True:
            data = src.read(src.in_waiting or 1)
            if data:
                dst.write(data)
                dst.flush()
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                logf.write(f"{ts} {label} {len(data)} bytes: {hexdump(data)}\n")
                logf.flush()
            else:
                time.sleep(0.01)
    except Exception as e:
        logf.write(f"FORWARD EXCEPTION {label}: {e}\n")
        logf.flush()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--phys", required=True, help="Physical COM port (device)")
    p.add_argument("--virt", required=True, help="Virtual COM port (app connects to this)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--log", default="serial_proxy.log")
    args = p.parse_args()

    logf = open(args.log, "a", buffering=1, encoding="utf-8")
    logf.write(f"=== Serial proxy starting: phys={args.phys} virt={args.virt} baud={args.baud}\n")

    try:
        ser_phys = serial.Serial(args.phys, args.baud, timeout=0)
    except Exception as e:
        logf.write(f"Error opening physical port {args.phys}: {e}\n")
        logf.close()
        print("Error opening physical port:", e)
        sys.exit(1)
    try:
        ser_virt = serial.Serial(args.virt, args.baud, timeout=0)
    except Exception as e:
        logf.write(f"Error opening virtual port {args.virt}: {e}\n")
        ser_phys.close()
        logf.close()
        print("Error opening virtual port:", e)
        sys.exit(1)

    t1 = threading.Thread(target=forward, args=(ser_virt, ser_phys, "V->P", logf), daemon=True)
    t2 = threading.Thread(target=forward, args=(ser_phys, ser_virt, "P->V", logf), daemon=True)
    t1.start(); t2.start()
    logf.write("Proxy threads started. Press Ctrl-C to exit.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logf.write("Proxy stopping (KeyboardInterrupt)\n")
    finally:
        ser_phys.close(); ser_virt.close(); logf.close()

if __name__ == "__main__":
    main()
