# src/actions/wallet/interface.py
from dataclasses import dataclass
from typing import Optional

from actions.base import Interface


@dataclass
class WalletInput:
    """
    Input for wallet operations.

    Parameters
    ----------
    action : str
        The wallet action to perform: "poll", "sign", "send", or "transfer"
    message : Optional[str]
        Message to sign (for "sign" action)
    to_address : Optional[str]
        Destination address (for "send" and "transfer" actions)
    amount : Optional[float]
        Amount to transfer in ETH (for "transfer" action)
    asset_id : Optional[str]
        Asset identifier (default: "eth")
    """

    action: str
    message: Optional[str] = None
    to_address: Optional[str] = None
    amount: Optional[float] = None
    asset_id: str = "eth"


@dataclass
class Wallet(Interface[WalletInput, WalletInput]):
    """
    This action allows you to interact with the Coinbase wallet.

    Supported actions:
    - poll: Check current wallet balance
    - sign: Sign a message with the wallet
    - send: Send a transaction
    - transfer: Transfer assets to another address
    """

    input: WalletInput
    output: WalletInput
