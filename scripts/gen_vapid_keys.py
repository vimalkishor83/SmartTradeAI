"""
Generate VAPID key pair for Web Push notifications.
Run once: python scripts/gen_vapid_keys.py
Then add the output to your .env file.
"""
import base64
from py_vapid import Vapid
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

v = Vapid()
v.generate_keys()

priv_pem = v.private_pem().decode()
pub_bytes = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()

print("Add these to your .env file:\n")
print(f"VAPID_PUBLIC_KEY={pub_b64}")
print(f'VAPID_PRIVATE_KEY="{priv_pem.strip()}"')
print("VAPID_CLAIMS_EMAIL=mailto:admin@smarttradeai.com")
