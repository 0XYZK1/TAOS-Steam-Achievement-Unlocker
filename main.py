import sys
import traceback


def _worker(argv):
    from taos.worker import run_steamworks_worker

    run_steamworks_worker(int(argv[2]), argv[3], argv[4] if len(argv) > 4 else "{}")


def _write_crash_log():
    from taos.config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "taos_error.log").write_text(traceback.format_exc(), encoding="utf-8")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--taos-worker":
        _worker(sys.argv)
        return

    try:
        from taos.app import main as run_app

        run_app()
    except Exception:
        try:
            _write_crash_log()
        except OSError:
            pass
        raise


if __name__ == "__main__":
    main()
