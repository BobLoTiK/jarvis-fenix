"""Initialize public defaults through Config/paths; never copy config into code root."""
import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-dependencies', action='store_true')
    args = parser.parse_args(argv)
    from jarvis import paths
    from jarvis.config import Config
    Config()  # Existing user config/profile data are not reset.
    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    paths.program_models_dir().mkdir(parents=True, exist_ok=True)
    print(f'Конфиг: {paths.config_path()}')
    print(f'Логи: {paths.logs_dir()}')
    print(f'Модели: {paths.program_models_dir()}')
    if args.record_dependencies:
        import logging
        from launcher import record_dependency_receipt, _probe_dependencies
        if not _probe_dependencies(BASE,logging.getLogger('setup')):
            print('Проверка окружения не прошла; receipt не записан.')
            return 1
        if not record_dependency_receipt(BASE):
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
