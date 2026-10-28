# Agent instructions

This project runs on chora-node, a shared machine. Before you bind a port, add a container,
install a package or create a service, read `docs/chora-node-map.md` and follow its house
rules, and follow `docs/python-on-chora-node.md` for anything Python.
- Never stop, remove or prune containers, images or volumes you did not create.
- Never restart or reconfigure the shared AI services.
- Never commit secrets or put tokens in git remote URLs.
