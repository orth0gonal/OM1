"""Wallet manager for orchestrating robot and user wallet providers."""
import logging
from typing import Optional

from .providers import CoinbaseProvider, UserWalletProvider, WalletInfo


class WalletManager:
    """
    Wallet manager to orchestrate between robot wallet (Coinbase) and user wallet (Browser).

    The robot wallet is owned by the robot and uses private key authentication.
    The user wallet is owned by the user and uses browser-based signing (MetaMask, WalletConnect).
    """

    def __init__(self, rpc_url: Optional[str] = None):
        """
        Initialize wallet manager.

        Parameters
        ----------
        rpc_url : Optional[str]
            RPC endpoint URL for robot wallet
        """
        self.robot_wallet = CoinbaseProvider(rpc_url=rpc_url)
        self.user_wallet = UserWalletProvider()
        self._robot_connected = False
        self._user_connected = False

    async def connect_robot_wallet(self) -> WalletInfo:
        """
        Connect robot wallet using ETH_PRIVATE_KEY.

        Returns
        -------
        WalletInfo
            Robot wallet information
        """
        wallet_info = await self.robot_wallet.connect()
        self._robot_connected = True
        logging.info(f"Robot wallet connected: {wallet_info.address}")
        return wallet_info

    def connect_user_wallet(
        self, address: str, chain_id: int, balance: Optional[float] = None
    ) -> None:
        """
        Connect user wallet with info from browser.

        Parameters
        ----------
        address : str
            User's wallet address
        chain_id : int
            Connected chain ID
        balance : Optional[float]
            Wallet balance
        """
        self.user_wallet.set_wallet_info(address, chain_id, balance)
        self._user_connected = True
        logging.info(f"User wallet connected: {address}")

    async def disconnect_robot_wallet(self) -> None:
        """Disconnect robot wallet."""
        await self.robot_wallet.disconnect()
        self._robot_connected = False
        logging.info("Robot wallet disconnected")

    async def disconnect_user_wallet(self) -> None:
        """Disconnect user wallet."""
        await self.user_wallet.disconnect()
        self._user_connected = False
        logging.info("User wallet disconnected")

    def is_robot_connected(self) -> bool:
        """Check if robot wallet is connected."""
        return self._robot_connected

    def is_user_connected(self) -> bool:
        """Check if user wallet is connected."""
        return self._user_connected

    async def robot_sign_message(self, message: str) -> str:
        """
        Sign message with robot wallet.

        Parameters
        ----------
        message : str
            Message to sign

        Returns
        -------
        str
            Signature in hex format
        """
        if not self._robot_connected:
            raise RuntimeError("Robot wallet not connected")
        return await self.robot_wallet.sign_message(message)

    async def robot_send_transaction(
        self, to_address: str, amount: float, data: Optional[str] = None
    ) -> str:
        """
        Send transaction from robot wallet.

        Parameters
        ----------
        to_address : str
            Destination address
        amount : float
            Amount in ETH
        data : Optional[str]
            Transaction data

        Returns
        -------
        str
            Transaction hash
        """
        if not self._robot_connected:
            raise RuntimeError("Robot wallet not connected")
        return await self.robot_wallet.send_transaction(to_address, amount, data)

    async def robot_get_balance(self, address: str) -> float:
        """
        Get balance for robot wallet.

        Parameters
        ----------
        address : str
            Wallet address

        Returns
        -------
        float
            Balance in ETH
        """
        if not self._robot_connected:
            raise RuntimeError("Robot wallet not connected")
        return await self.robot_wallet.get_balance(address)

    def process_user_signature(
        self, message: str, signature: str, from_address: str
    ) -> dict:
        """
        Process a signature received from user's browser wallet.

        Parameters
        ----------
        message : str
            Original message that was signed
        signature : str
            Signature from user's wallet
        from_address : str
            User's wallet address

        Returns
        -------
        dict
            Processing result with status and details
        """
        if not self._user_connected:
            return {
                "status": "error",
                "message": "User wallet not connected",
            }

        # Verify the signature came from the connected user
        if self.user_wallet.wallet_info.address.lower() != from_address.lower():
            return {
                "status": "error",
                "message": "Signature address does not match connected wallet",
            }

        logging.info(
            f"User signature processed: {from_address} signed '{message}' -> {signature[:20]}..."
        )

        return {
            "status": "success",
            "message": "Signature verified and processed",
            "data": {
                "from_address": from_address,
                "message": message,
                "signature": signature,
            },
        }

    def process_user_transaction(
        self, from_address: str, to_address: str, amount: float, tx_hash: str
    ) -> dict:
        """
        Process a transaction received from user's browser wallet.

        Parameters
        ----------
        from_address : str
            User's wallet address
        to_address : str
            Destination address
        amount : float
            Amount in ETH
        tx_hash : str
            Transaction hash

        Returns
        -------
        dict
            Processing result with status and details
        """
        if not self._user_connected:
            return {
                "status": "error",
                "message": "User wallet not connected",
            }

        # Verify the transaction came from the connected user
        if self.user_wallet.wallet_info.address.lower() != from_address.lower():
            return {
                "status": "error",
                "message": "Transaction address does not match connected wallet",
            }

        logging.info(
            f"User transaction processed: {from_address} -> {to_address} | {amount} ETH | Tx: {tx_hash}"
        )

        return {
            "status": "success",
            "message": "Transaction verified and processed",
            "data": {
                "from_address": from_address,
                "to_address": to_address,
                "amount": amount,
                "tx_hash": tx_hash,
            },
        }
