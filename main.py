import sys


def _worker(argv):
    from taos.worker import run_steamworks_worker

    run_steamworks_worker(int(argv[2]), argv[3], argv[4] if len(argv) > 4 else "{}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--taos-worker":
        _worker(sys.argv)
        return

    from taos.app import main as run_app

    run_app()


if __name__ == "__main__":
    main()
