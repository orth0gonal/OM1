import asyncio
import logging
import os
import time
import typing

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from actions.base import ActionConfig, ActionConnector
from actions.wallet.interface import WalletInput
from providers.io_provider import IOProvider


class WalletCoinbaseConnector(ActionConnector[WalletInput]):
    """
    Ethereum wallet connector for blockchain operations.
    Supports polling balance, signing messages, and transferring assets using private key.
    """

    def __init__(self, config: ActionConfig):
        """
        Initialize the Ethereum wallet connector.

        Parameters
        ----------
        config : ActionConfig
            Configuration for the connector.
        """
        super().__init__(config)

        self.io_provider = IOProvider()
        self.account: typing.Optional[Account] = None
        self.w3: typing.Optional[Web3] = None

        # Get private key from environment
        private_key = os.environ.get("ETH_PRIVATE_KEY")
        if not private_key:
            logging.error("ETH_PRIVATE_KEY environment variable is not set")
            return

        # Get RPC URL (default to Base Sepolia testnet)
        rpc_url = os.environ.get("ETH_RPC_URL", "https://sepolia.base.org")

        try:
            # Initialize Web3 connection
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))

            # Create account from private key
            if not private_key.startswith("0x"):
                private_key = "0x" + private_key
            self.account = Account.from_key(private_key)

            logging.info(f"WalletConnector initialized with address: {self.account.address}")
            logging.info(f"Connected to network: {rpc_url}")
        except Exception as e:
            logging.error(f"Error initializing wallet: {e}")
            self.account = None
            self.w3 = None

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
            self.io_provider.add_input("WalletStatus", message, time.time())
        except Exception as e:
            logging.warning("WalletStatus write failed: %s", e)

    async def _poll_balance(self, asset_id: str) -> None:
        """
        Poll and report current wallet balance.

        Parameters
        ----------
        asset_id : str
            Asset identifier (e.g., "eth").
        """
        if not self.account or not self.w3:
            logging.error("Wallet not initialized")
            self._write_status("poll", "failed", "reason=wallet_not_initialized")
            return

        try:
            loop = asyncio.get_running_loop()
            # Get balance in Wei and convert to Ether
            balance_wei = await loop.run_in_executor(
                None, self.w3.eth.get_balance, self.account.address
            )
            balance = float(self.w3.from_wei(balance_wei, 'ether'))

            logging.info(f"Wallet balance: {balance} {asset_id.upper()}")
            self._write_status(
                "poll", "success", f"balance={balance} asset={asset_id} address={self.account.address}"
            )
        except Exception as e:
            logging.error(f"Error polling balance: {e}")
            self._write_status("poll", "failed", f"reason={str(e)}")

    async def _sign_message(self, message: str) -> None:
        """
        Sign a message with the wallet.

        Parameters
        ----------
        message : str
            Message to sign.
        """
        if not self.account:
            logging.error("Wallet not initialized")
            self._write_status("sign", "failed", "reason=wallet_not_initialized")
            return

        try:
            loop = asyncio.get_running_loop()
            # Encode message for Ethereum signing
            encoded_message = encode_defunct(text=message)

            # Sign message using eth_account
            signed_message = await loop.run_in_executor(
                None, self.account.sign_message, encoded_message
            )

            signature_hex = signed_message.signature.hex()
            logging.info(f"Message signed: {signature_hex}")
            self._write_status("sign", "success", f"signature={signature_hex}")
        except Exception as e:
            logging.error(f"Error signing message: {e}")
            self._write_status("sign", "failed", f"reason={str(e)}")

    async def _send_transaction(self, to_address: str, asset_id: str) -> None:
        """
        Send a transaction (placeholder - use transfer for actual ETH transfers).

        Parameters
        ----------
        to_address : str
            Destination address.
        asset_id : str
            Asset identifier.
        """
        logging.info("Use 'transfer' action for actual ETH transfers")
        self._write_status(
            "send", "failed", "reason=use_transfer_action_instead"
        )

    async def _transfer_assets(
        self, to_address: str, amount: float, asset_id: str
    ) -> None:
        """
        Transfer ETH to another address.

        Parameters
        ----------
        to_address : str
            Destination address.
        amount : float
            Amount to transfer in ETH.
        asset_id : str
            Asset identifier (e.g., "eth").
        """
        if not self.account or not self.w3:
            logging.error("Wallet not initialized")
            self._write_status("transfer", "failed", "reason=wallet_not_initialized")
            return

        try:
            loop = asyncio.get_running_loop()

            # Build transaction
            def _build_and_send_tx():
                # Get current nonce
                nonce = self.w3.eth.get_transaction_count(self.account.address)

                # Get gas price
                gas_price = self.w3.eth.gas_price

                # Convert amount to Wei
                value_wei = self.w3.to_wei(amount, 'ether')

                # Build transaction
                transaction = {
                    'nonce': nonce,
                    'to': self.w3.to_checksum_address(to_address),
                    'value': value_wei,
                    'gas': 21000,  # Standard ETH transfer gas limit
                    'gasPrice': gas_price,
                    'chainId': self.w3.eth.chain_id,
                }

                # Sign transaction
                signed_txn = self.account.sign_transaction(transaction)

                # Send transaction
                tx_hash = self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)

                # Wait for transaction receipt
                tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                return tx_hash.hex(), tx_receipt

            tx_hash, tx_receipt = await loop.run_in_executor(None, _build_and_send_tx)

            logging.info(
                f"Transfer completed: {amount} {asset_id.upper()} to {to_address}"
            )
            logging.info(f"Transaction hash: {tx_hash}")
            self._write_status(
                "transfer",
                "success",
                f"amount={amount} asset={asset_id} to={to_address} tx_hash={tx_hash} status={tx_receipt['status']}",
            )
        except Exception as e:
            logging.error(f"Error transferring assets: {e}")
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

        asset_id = (output_interface.asset_id or "eth").strip().lower()

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
            logging.error(f"Unknown wallet action: {action}")
            self._write_status(action, "failed", "reason=unknown_action")
