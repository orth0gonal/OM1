"""User wallet provider for browser-based wallet interactions."""
import logging
from typing import Optional

from .base import WalletInfo, WalletProvider


class UserWalletProvider(WalletProvider):
    """
    User wallet provider for browser-based wallets.
    This provider handles wallet actions that are signed in the user's browser
    (MetaMask, WalletConnect, etc.) and transmitted to the robot.
    """

    def __init__(self):
        """Initialize User wallet provider."""
        self.wallet_info: Optional[WalletInfo] = None

    async def connect(self) -> WalletInfo:
        """
        Connect is handled in the browser.
        This method returns the stored wallet info if available.
        """
        if not self.wallet_info:
            raise RuntimeError(
                "User wallet not connected. Connection must happen in browser."
            )
        return self.wallet_info

    def set_wallet_info(
        self, address: str, chain_id: int, balance: Optional[float] = None
    ) -> None:
        """
        Set wallet info from browser connection.

        Parameters
        ----------
        address : str
            User's wallet address
        chain_id : int
            Connected chain ID
        balance : Optional[float]
            Wallet balance (if available)
        """
        self.wallet_info = WalletInfo(
            address=address,
            chain_id=chain_id,
            balance=balance,
            provider_name="user_browser",
        )
        logging.info(f"User wallet info set: {address} on chain {chain_id}")

    async def get_balance(self, address: str) -> float:
        """
        Get wallet balance.
        For user wallets, balance is fetched in the browser.
        """
        if not self.wallet_info:
            raise RuntimeError("User wallet not connected")

        if self.wallet_info.balance is None:
            logging.warning("Balance not available for user wallet")
            return 0.0

        return self.wallet_info.balance

    async def sign_message(self, message: str) -> str:
        """
        Sign a message.
        For user wallets, signing happens in the browser.
        This method should not be called directly.
        """
        raise NotImplementedError(
            "User wallet signing must happen in the browser. "
            "Use browser wallet UI to sign messages."
        )

    async def send_transaction(
        self, to_address: str, amount: float, data: Optional[str] = None
    ) -> str:
        """
        Send a transaction.
        For user wallets, transactions are created and signed in the browser.
        This method should not be called directly.
        """
        raise NotImplementedError(
            "User wallet transactions must happen in the browser. "
            "Use browser wallet UI to send transactions."
        )

    async def disconnect(self) -> None:
        """Disconnect from wallet."""
        self.wallet_info = None
        logging.info("User wallet disconnected")
