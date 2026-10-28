"""Run local API, worker and Next.js in one terminal. Ctrl+C stops all three."""
import os
import subprocess
import sys
import time
from pathlib import Path

from db import migrate
from security import cipher


def main():
    root = Path(__file__).parent.parent
    cipher()
    migrate()
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    commands = [
        ([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','8000'], root/'backend'),
        ([sys.executable,'worker.py'], root/'backend'),
        (['node',str(root/'node_modules/next/dist/bin/next'),'dev','--hostname','127.0.0.1','--port','3000'],root),
    ]
    processes=[]
    try:
        for command,cwd in commands:
            processes.append(subprocess.Popen(command,cwd=cwd,creationflags=flags))
        print('Ai Notify: http://localhost:3000 | API: http://127.0.0.1:8000/docs',flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(.5)
        raise SystemExit('A service stopped. Check the error above.')
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == '__main__':
    main()
