import os
import time
from pathlib import Path

def cleanup_media(directory: str, max_age_hours: int = 24):
    """
    Delete files in the specified directory older than max_age_hours.
    """
    path = Path(directory)
    if not path.exists():
        return
    
    now = time.time()
    count = 0
    
    for item in path.iterdir():
        if item.is_file():
            # Get file modification time
            file_age = now - item.stat().st_mtime
            if file_age > (max_age_hours * 3600):
                try:
                    item.unlink()
                    count += 1
                except Exception as e:
                    print(f"Failed to delete {item}: {e}")
                    
    return count

if __name__ == "__main__":
    # Test cleanup
    base_dir = Path(__file__).resolve().parent
    upload_dir = base_dir / "instance" / "uploads"
    deleted = cleanup_media(str(upload_dir))
    print(f"Cleaned up {deleted} old files.")
