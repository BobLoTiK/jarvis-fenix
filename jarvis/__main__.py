from jarvis.https_trust import configure_https_trust

# Must run before Flet/torch and before any first-use download.
configure_https_trust()

from jarvis.main import main

if __name__ == "__main__":
    main()
