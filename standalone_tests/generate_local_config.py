# SPDX-License-Identifier: Unlicense
"""Generate config.generated.yaml from config.mock.template.yaml for local testing."""
import sys
import os


def generate() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, "config.mock.template.yaml")
    mock_script = os.path.join(base_dir, "mock_wp.py")

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template not found: {template_path}")

    python_exe = sys.executable.replace("\\", "/")
    mock_script_abs = os.path.abspath(mock_script).replace("\\", "/")

    with open(template_path) as f:
        content = f.read()

    content = content.replace("{python}", python_exe).replace("{mock_script}", mock_script_abs)

    config_path = os.path.join(base_dir, "config.generated.yaml")
    with open(config_path, "w") as f:
        f.write(content)

    print(f"[*] Generated {config_path}")
    return config_path


if __name__ == "__main__":
    generate()
