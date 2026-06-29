"""Quick setup script — installs dependencies and initializes the database."""
import subprocess
import sys
import os

def run(cmd):
    print(f"► {cmd}")
    subprocess.check_call(cmd, shell=True)

if __name__ == "__main__":
    print("=== SmartTrade AI Platform Setup ===\n")

    # Install dependencies
    run(f"{sys.executable} -m pip install -r requirements.txt")

    # Copy .env if not exists
    if not os.path.exists(".env"):
        import shutil
        shutil.copy(".env.example", ".env")
        print("\n✓ Created .env from .env.example — please review and update credentials")

    print("\n✓ Setup complete! Run the app with:\n")
    print("   python run.py\n")
