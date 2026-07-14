.DEFAULT_GOAL := help
.PHONY: help test rebalance rebalance-execute

# eToro tarpits authenticated requests from the home IP; traffic must egress
# through the vida server (see ETORO_TUNNEL). Keys must whitelist that IP.
ETORO_TUNNEL = nc -z 127.0.0.1 1080 2>/dev/null || ssh -D 1080 -N -f vida
ETORO_PROXY = HTTPS_PROXY=socks5h://127.0.0.1:1080

help:
	@echo "  test               Run the test suite"
	@echo "  rebalance          Preview eToro rebalance (dry-run, no orders placed)"
	@echo "  rebalance-execute  Rebalance eToro portfolio for real (places orders)"

test:
	uv run python -m pytest

rebalance:
	@$(ETORO_TUNNEL)
	$(ETORO_PROXY) uv run python scripts/rebalance_etoro.py

rebalance-execute:
	@$(ETORO_TUNNEL)
	$(ETORO_PROXY) uv run python scripts/rebalance_etoro.py --execute
