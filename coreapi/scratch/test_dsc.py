import pkcs11
from pkcs11 import lib, Token, Slot
import os

# The driver we found
LIB_PATH = r"C:\Windows\System32\InnaITPKCS11Driver.dll"

def detect_token():
    print(f"--- Attempting to load: {LIB_PATH} ---")
    if not os.path.exists(LIB_PATH):
        print("ERROR: Library path does not exist!")
        return

    try:
        # Load the PKCS#11 library
        _lib = pkcs11.lib(LIB_PATH)
        print("Library loaded successfully.")

        # List available slots
        slots = _lib.get_slots()
        print(f"Found {len(slots)} slots.")

        for i, slot in enumerate(slots):
            print(f"\nSlot {i}: {slot.slot_description}")
            try:
                token = slot.get_token()
                print(f"  Token: {token.label}")
                print(f"  Manufacturer: {token.manufacturer_id}")
                print(f"  Serial: {token.serial_number}")
            except pkcs11.exceptions.NoSuchToken:
                print("  (No token in this slot)")

    except Exception as e:
        print(f"ERROR: {str(e)}")

if __name__ == "__main__":
    detect_token()
