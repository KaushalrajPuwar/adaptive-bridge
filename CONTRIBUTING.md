# Contributing to Adaptive Bridge

Thank you for your interest in Adaptive Bridge! This document provides
guidelines for contributions, development workflow, and code standards.

## Code of Conduct

This project is governed by basic open-source etiquette. Be respectful,
constructive, and collaborative.

## Getting Started

1. Fork the repository.
2. Create a feature branch from `main`.
3. Make your changes following the guidelines below.
4. Run the test suite.
5. Submit a pull request with a clear description of your changes.

## Development Setup

```bash
# Clone your fork
git clone https://github.com/KaushalrajPuwar/adaptive-bridge.git
cd adaptive-bridge

# Build
colcon build --packages-select adaptive_bridge
source install/setup.bash

# Run tests
colcon test --packages-select adaptive_bridge
colcon test-result --verbose
```

## Code Standards

### Python

- **Python 3.12+** target.
- **Type annotations** required for all function signatures.
- **f-strings** preferred over `%` or `.format()`.
- Follow PEP 8 for code style and PEP 257 for docstrings.
- Module-level docstrings are required for all core modules.
- Class docstrings should describe the class's responsibility and
  public interface.

### Import Order

```
from __future__ import annotations

# Standard library
import os
import sys

# Third-party
import yaml
from rclpy.qos import QoSProfile

# First-party
from .models import TopicRoute
```

### Commit Messages

- Use the imperative mood ("Add feature" not "Added feature").
- Reference issue numbers when applicable.
- Keep the first line under 72 characters.

## Pull Request Process

1. Ensure all tests pass before submitting.
2. Update documentation if adding or changing features.
3. Add or update tests for new functionality.
4. The PR description should explain:
   - What the change does
   - Why it's needed
   - How it was tested

## Adding a New Message Type

1. Add the message package to `package.xml` dependencies.
2. Configure the topic in your YAML config:
   ```yaml
   topics:
     - id: "my_topic"
       input_topic: "/my/input"
       critical_output: "/adaptive_bridge/critical/my"
       noncritical_output: "/adaptive_bridge/noncritical/my"
       message_type: "my_package/MyMsg"
   ```
3. Ensure `my_package` is installed in your ROS 2 environment.

## Running Evaluation Experiments

See `eval/README.md` for the experiment harness.

## Issue Reporting

When reporting issues, include:

- ROS 2 distribution and DDS vendor
- Configuration file (or relevant section)
- Steps to reproduce
- Expected vs actual behaviour
- Relevant logs or error messages

## License

By contributing, you agree that your contributions will be licensed under
the Apache License 2.0.
