# SPDX-License-Identifier: Unlicense
import sys
import json


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("WP-CLI mock", flush=True)
        return

    # Simple routing based on arguments
    cmd_str = " ".join(args)

    # Check for --format=json
    is_json = "--format=json" in args or "--json" in args

    if "core version" in cmd_str:
        print("6.5.2", flush=True)
    elif "core check-update" in cmd_str:
        updates = [
            {"version": "6.5.3", "update_type": "minor", "package_url": "https://example.com"}
        ]
        print(json.dumps(updates) if is_json else "WordPress 6.5.3 is available.", flush=True)
    elif "plugin list" in cmd_str:
        plugins = [
            {"name": "akismet", "status": "active", "version": "5.3.2"},
            {"name": "hello-dolly", "status": "inactive", "version": "1.7.2"},
        ]
        print(
            json.dumps(plugins) if is_json else "akismet active 5.3.2\nhello-dolly inactive 1.7.2",
            flush=True,
        )
    elif "theme list" in cmd_str:
        themes = [{"name": "twentytwentyfour", "status": "active", "version": "1.1"}]
        print(json.dumps(themes) if is_json else "twentytwentyfour active 1.1", flush=True)
    elif "db check" in cmd_str:
        print("Success: Database check completed.", flush=True)
    elif "db tables" in cmd_str:
        tables = ["wp_posts", "wp_users", "wp_options"]
        print(json.dumps(tables) if is_json else "\n".join(tables), flush=True)
    elif "cache flush" in cmd_str:
        print("Success: The object cache was flushed.", flush=True)
    else:
        # Fallback for other commands
        print(f"Mock WP: Executed '{cmd_str}'", flush=True)


if __name__ == "__main__":
    main()
