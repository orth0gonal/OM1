"""Base wallet provider interface for OM1 wallet-agnostic architecture."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class WalletInfo:
    """Wallet information."""
    address: str
    chain_id: int
    balance: Optional[float] = None
    provider_name: str = "unknown"


class WalletProvider(ABC):
    """Abstract base class for wallet providers."""

    @abstractmethod
    async def connect(self) -> WalletInfo:
        """
        Connect to the wallet.

        Returns
        -------
        WalletInfo
            Connected wallet information.
        """
        pass

    @abstractmethod
    async def get_balance(self, address: str) -> float:
        """
        Get wallet balance.

        Parameters
        ----------
        address : str
            Wallet address.

        Returns
        -------
        float
            Balance in ETH.
        """
        pass

    @abstractmethod
    async def sign_message(self, message: str) -> str:
        """
        Sign a message.

        Parameters
        ----------
        message : str
            Message to sign.

        Returns
        -------
        str
            Signature in hex format.
        """
        pass

    @abstractmethod
    async def send_transaction(
        self, to_address: str, amount: float, data: Optional[str] = None
    ) -> str:
        """
        Send a transaction.

        Parameters
        ----------
        to_address : str
            Destination address.
        amount : float
            Amount in ETH.
        data : Optional[str]
            Transaction data (optional).

        Returns
        -------
        str
            Transaction hash.
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the wallet."""
        pass
