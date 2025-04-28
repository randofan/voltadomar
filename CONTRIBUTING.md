# Contributing to Voltadomar

Thank you for your interest in contributing to Voltadomar! This document provides guidelines and instructions for contributing.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## How Can I Contribute?

### Reporting Bugs

- Before creating a bug report, check the issue tracker to see if the problem has already been reported
- Use the bug report template to create a new issue
- Provide detailed steps to reproduce the problem
- Include relevant details about your environment (OS, Python version, etc.)

### Suggesting Enhancements

- Before creating an enhancement suggestion, check the issue tracker
- Use the feature request template to create a new issue
- Provide a clear description of the enhancement and its benefits

### Pull Requests

1. Fork the repository
2. Create a new branch for your feature or bugfix (`git checkout -b feature/amazing-feature`)
3. Make your changes, following our coding standards
4. Add appropriate tests for your changes
5. Ensure all tests pass
6. Update documentation as needed
7. Submit your pull request with a clear description of the changes

## Development Setup

1. Clone your fork of the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

## Coding Standards

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guidelines
- Write docstrings for all functions, classes, and methods
- Include type hints where appropriate
- Use descriptive variable names

## Testing

- TODO

## Documentation

- Update documentation for any changes to public APIs
- Write clear, concise explanations
- Include examples where helpful

## Commit Messages

- Use the present tense ("Add feature" not "Added feature")
- Use the imperative mood ("Move cursor to..." not "Moves cursor to...")
- Reference issues and pull requests where appropriate

## Release Process

- TODO

## Questions?

If you have any questions about contributing, please open an issue or contact the maintainers.

Thank you for contributing to Voltadomar!
