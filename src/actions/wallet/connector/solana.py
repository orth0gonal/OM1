import asyncio
import base58
import json
import logging
import os
import time
import typing

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

from actions.base import ActionConfig, ActionConnector
from actions.wallet.interface import WalletInput
from providers.io_provider import IOProvider


class WalletSolanaConnector(ActionConnector[WalletInput]):
    """
    Solana wallet connector for blockchain operations.
    Supports polling balance, signing messages, and transferring assets using private key.
    """

    def __init__(self, config: ActionConfig):
        """
        Initialize the Solana wallet connector.

        Parameters
        ----------
        config : ActionConfig
            Configuration for the connector.
        """
        super().__init__(config)

        self.io_provider = IOProvider()
        self.keypair: typing.Optional[Keypair] = None
        self.client: typing.Optional[AsyncClient] = None
        self.pubkey: typing.Optional[Pubkey] = None

        # Get private key from environment
        private_key = os.environ.get("SOLANA_PRIVATE_KEY")
        if not private_key:
            logging.error("SOLANA_PRIVATE_KEY environment variable is not set")
            return

        # Get RPC URL (default to Devnet)
        rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")

        try:
            # Initialize Solana client
            self.client = AsyncClient(rpc_url, commitment=Confirmed)

            # Create keypair from private key
            # Support both base58 string and JSON array formats
            if private_key.startswith("["):
                # JSON array format: [1,2,3,...]
                key_bytes = bytes(json.loads(private_key))
            else:
                # Base58 format
                key_bytes = base58.b58decode(private_key)

            self.keypair = Keypair.from_bytes(key_bytes)
            self.pubkey = self.keypair.pubkey()

            logging.info(f"WalletSolanaConnector initialized with address: {self.pubkey}")
            logging.info(f"Connected to network: {rpc_url}")
        except Exception as e:
            logging.error(f"Error initializing Solana wallet: {e}")
            self.keypair = None
            self.client = None
            self.pubkey = None

    def _write_status(self, action: str, status: str, details: str = ""):
        """
        Write wallet operation status to IOProvider.

        Parameters
        ----------
        action : str
            The wallet action performed (poll, sign, send, transfer).
        status : str
            Status of the operation (success, failed).
        details : str, optional
            Additional details about the operation.
        """
        try:
            message = f"action={action} status={status}"
            if details:
                message += f" {details}"
            self.io_provider.add_input("WalletSolanaStatus", message, time.time())
        except Exception as e:
            logging.warning("WalletSolanaStatus write failed: %s", e)

    async def _poll_balance(self, asset_id: str) -> None:
        """
        Poll and report current wallet balance.

        Parameters
        ----------
        asset_id : str
            Asset identifier (e.g., "sol").
        """
        if not self.keypair or not self.client or not self.pubkey:
            logging.error("Solana wallet not initialized")
            self._write_status("poll", "failed", "reason=wallet_not_initialized")
            return

        try:
            # Get balance in lamports and convert to SOL
            response = await self.client.get_balance(self.pubkey)
            balance_lamports = response.value
            balance = float(balance_lamports) / 1_000_000_000

            logging.info(f"Solana wallet balance: {balance} {asset_id.upper()}")
            self._write_status(
                "poll", "success", f"balance={balance} asset={asset_id} address={self.pubkey}"
            )
        except Exception as e:
            logging.error(f"Error polling Solana balance: {e}")
            self._write_status("poll", "failed", f"reason={str(e)}")

    async def _sign_message(self, message: str) -> None:
        """
        Sign a message with the Solana wallet.

        Parameters
        ----------
        message : str
            Message to sign.
        """
        if not self.keypair:
            logging.error("Solana wallet not initialized")
            self._write_status("sign", "failed", "reason=wallet_not_initialized")
            return

        try:
            # Encode message to bytes
            message_bytes = message.encode('utf-8')

            # Sign message
            signature = self.keypair.sign_message(message_bytes)

            # Convert signature to base58 for readability
            signature_base58 = base58.b58encode(bytes(signature)).decode('utf-8')
            logging.info(f"Solana message signed: {signature_base58}")
            self._write_status("sign", "success", f"signature={signature_base58}")
        except Exception as e:
            logging.error(f"Error signing Solana message: {e}")
            self._write_status("sign", "failed", f"reason={str(e)}")

    async def _send_transaction(self, to_address: str, asset_id: str) -> None:
        """
        Send a transaction (placeholder - use transfer for actual SOL transfers).

        Parameters
        ----------
        to_address : str
            Destination address.
        asset_id : str
            Asset identifier.
        """
        logging.info("Use 'transfer' action for actual SOL transfers")
        self._write_status(
            "send", "failed", "reason=use_transfer_action_instead"
        )

    async def _transfer_assets(
        self, to_address: str, amount: float, asset_id: str
    ) -> None:
        """
        Transfer SOL to another address.

        Parameters
        ----------
        to_address : str
            Destination address (base58 public key).
        amount : float
            Amount to transfer in SOL.
        asset_id : str
            Asset identifier (e.g., "sol").
        """
        if not self.keypair or not self.client or not self.pubkey:
            logging.error("Solana wallet not initialized")
            self._write_status("transfer", "failed", "reason=wallet_not_initialized")
            return

        try:
            # Convert destination address to Pubkey
            to_pubkey = Pubkey.from_string(to_address)

            # Convert SOL to lamports
            lamports = int(amount * 1_000_000_000)

            # Create transfer instruction
            transfer_ix = transfer(
                TransferParams(
                    from_pubkey=self.pubkey,
                    to_pubkey=to_pubkey,
                    lamports=lamports
                )
            )

            # Get recent blockhash
            blockhash_response = await self.client.get_latest_blockhash()
            recent_blockhash = blockhash_response.value.blockhash

            # Create and sign transaction
            transaction = Transaction.new_with_payer(
                [transfer_ix],
                self.pubkey,
            )
            transaction.recent_blockhash = recent_blockhash
            transaction.sign([self.keypair])

            # Send transaction
            send_response = await self.client.send_transaction(transaction)
            tx_signature = str(send_response.value)

            # Wait for confirmation
            confirm_response = await self.client.confirm_transaction(
                send_response.value,
                commitment=Confirmed
            )

            logging.info(
                f"Solana transfer completed: {amount} {asset_id.upper()} to {to_address}"
            )
            logging.info(f"Transaction signature: {tx_signature}")
            self._write_status(
                "transfer",
                "success",
                f"amount={amount} asset={asset_id} to={to_address} tx_signature={tx_signature}",
            )
        except Exception as e:
            logging.error(f"Error transferring Solana assets: {e}")
            self._write_status("transfer", "failed", f"reason={str(e)}")

    async def connect(self, output_interface: WalletInput) -> None:
        """
        Execute the requested wallet operation.

        Parameters
        ----------
        output_interface : WalletInput
            The wallet action interface containing operation parameters.
        """
        # Parse action string - format can be "poll", "sign:message", "transfer:address:amount"
        action_str = (output_interface.action or "").strip()
        parts = action_str.split(":")
        action = parts[0].lower()

        # Parse additional parameters from action string if present
        if len(parts) > 1:
            if action == "sign":
                output_interface.message = ":".join(parts[1:])  # rejoin in case message contains ":"
            elif action == "transfer" and len(parts) >= 3:
                output_interface.to_address = parts[1]
                try:
                    output_interface.amount = float(parts[2])
                except ValueError:
                    logging.error(f"Invalid amount in transfer action: {parts[2]}")
            elif action == "send" and len(parts) >= 2:
                output_interface.to_address = parts[1]

        asset_id = (output_interface.asset_id or "sol").strip().lower()

        if action == "poll":
            await self._poll_balance(asset_id)

        elif action == "sign":
            if not output_interface.message:
                logging.error("Sign action requires a message")
                self._write_status("sign", "failed", "reason=missing_message")
                return
            await self._sign_message(output_interface.message)

        elif action == "send":
            if not output_interface.to_address:
                logging.error("Send action requires a to_address")
                self._write_status("send", "failed", "reason=missing_to_address")
                return
            await self._send_transaction(output_interface.to_address, asset_id)

        elif action == "transfer":
            if not output_interface.to_address or output_interface.amount is None:
                logging.error("Transfer action requires to_address and amount")
                self._write_status(
                    "transfer", "failed", "reason=missing_parameters"
                )
                return
            await self._transfer_assets(
                output_interface.to_address, output_interface.amount, asset_id
            )

        else:
            logging.error(f"Unknown Solana wallet action: {action}")
            self._write_status(action, "failed", "reason=unknown_action")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup client"""
        if self.client:
            await self.client.close()
