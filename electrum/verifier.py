# Electrum - Lightweight Bitcoin Client
# Copyright (c) 2012 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import asyncio
from typing import Sequence, Optional, TYPE_CHECKING

import aiorpcx

from .three_keys.transaction import TxType
from .util import bh2u, TxMinedInfo, NetworkJobOnDefaultServer
from .crypto import sha256d
from .bitcoin import hash_decode, hash_encode
from .transaction import Transaction
from .blockchain import hash_header
from .interface import GracefulDisconnect
from .network import UntrustedServerReturnedError
from . import constants

if TYPE_CHECKING:
    from .network import Network
    from .address_synchronizer import AddressSynchronizer


class MerkleVerificationFailure(Exception): pass
class MissingBlockHeader(MerkleVerificationFailure): pass
class MerkleRootMismatch(MerkleVerificationFailure): pass
class InnerNodeOfSpvProofIsValidTx(MerkleVerificationFailure): pass


class SPV(NetworkJobOnDefaultServer):
    """ Simple Payment Verification """

    def __init__(self, network: 'Network', wallet: 'AddressSynchronizer'):
        self.wallet = wallet
        NetworkJobOnDefaultServer.__init__(self, network)

    def _reset(self):
        super()._reset()
        self.merkle_roots = {}  # txid -> merkle root (once it has been verified)
        self.requested_merkle = set()  # txid set of pending requests

    async def _start_tasks(self):
        async with self.group as group:
            await group.spawn(self.main)

    def diagnostic_name(self):
        return self.wallet.diagnostic_name()

    async def main(self):
        self.blockchain = self.network.blockchain()
        while True:
            await self._maybe_undo_verifications()
            await self._request_proofs()
            await asyncio.sleep(0.1)

    async def _request_proofs(self):
        local_height = self.blockchain.height()
        unverified = self.wallet.get_unverified_txs()

        for tx_hash in unverified:
            # set NonVault tx_type if tx_type not exist in unverified items
            tx_type = TxType.NONVAULT
            if isinstance(unverified[tx_hash], tuple):
                tx_height, tx_type = unverified[tx_hash]
            else:
                tx_height = unverified[tx_hash]
            # do not request merkle branch if we already requested it
            if tx_hash in self.requested_merkle or tx_hash in self.merkle_roots:
                continue
            # or before headers are available
            if tx_height <= 0 or tx_height > local_height:
                continue
            # verify ALERT_PENDING & ALERT_RECOVERED txs without merkle check
            if tx_type == TxType.ALERT_PENDING.name or tx_type == TxType.ALERT_RECOVERED.name:
                await self.group.spawn(self._mark_as_verified, tx_hash, tx_height, tx_type)
                continue
            # if it's in the checkpoint region, we still might not have the header
            header = self.blockchain.read_header(tx_height)
            if header is None:
                if tx_height < constants.net.max_checkpoint():
                    await self.group.spawn(self.network.request_chunk(tx_height, None, can_return_early=True))
                continue
            # request now
            self.logger.info(f'requested merkle {tx_hash}')
            self.requested_merkle.add(tx_hash)
            await self.group.spawn(self._request_and_verify_single_proof, tx_hash, tx_height, tx_type)

    async def _mark_as_verified(self, tx_hash, tx_height, tx_type):
        self.requested_merkle.discard(tx_hash)
        self.logger.info(f"verified {tx_hash}")
        header = self.network.blockchain().read_header(tx_height)
        header_hash = hash_header(header)
        tx_info = TxMinedInfo(height=tx_height,
                              timestamp=header.get('timestamp'),
                              txpos=0,
                              header_hash=header_hash,
                              txtype=tx_type)
        self.wallet.add_verified_tx(tx_hash, tx_info)

    async def _request_and_verify_single_proof(self, tx_hash, tx_height, tx_type):
        # we need to wait if header sync/reorg is still ongoing, hence lock:
        tx_pos = -1
        async with self.network.bhi_lock:
            header = self.network.blockchain().read_header(tx_height)
        try:
            tx_pos = await verify_tx_is_in_block(self.network, tx_hash, header, tx_height)
        except MerkleVerificationFailure as e:
            if self.network.config.get("skipmerklecheck"):
                self.logger.info(f"skipping merkle proof check {tx_hash}")
            else:
                self.logger.info(repr(e))
                raise GracefulDisconnect(e) from e
        # we passed all the tests
        self.merkle_roots[tx_hash] = header.get('merkle_root')
        self.requested_merkle.discard(tx_hash)
        self.logger.info(f"verified {tx_hash}")
        header_hash = hash_header(header)
        tx_info = TxMinedInfo(height=tx_height,
                              timestamp=header.get('timestamp'),
                              txpos=tx_pos,
                              header_hash=header_hash,
                              txtype=tx_type)
        self.wallet.add_verified_tx(tx_hash, tx_info)

    @classmethod
    def hash_merkle_root(cls, merkle_branch: Sequence[str], tx_hash: str, leaf_pos_in_tree: int):
        """Return calculated merkle root."""
        try:
            h = hash_decode(tx_hash)
            merkle_branch_bytes = [hash_decode(item) for item in merkle_branch]
            leaf_pos_in_tree = int(leaf_pos_in_tree)  # raise if invalid
        except Exception as e:
            raise MerkleVerificationFailure(e)
        if leaf_pos_in_tree < 0:
            raise MerkleVerificationFailure('leaf_pos_in_tree must be non-negative')
        index = leaf_pos_in_tree
        for item in merkle_branch_bytes:
            if len(item) != 32:
                raise MerkleVerificationFailure('all merkle branch items have to 32 bytes long')
            h = sha256d(item + h) if (index & 1) else sha256d(h + item)
            index >>= 1
            cls._raise_if_valid_tx(bh2u(h))
        if index != 0:
            raise MerkleVerificationFailure(f'leaf_pos_in_tree too large for branch')
        return hash_encode(h)

    @classmethod
    def _raise_if_valid_tx(cls, raw_tx: str):
        # If an inner node of the merkle proof is also a valid tx, chances are, this is an attack.
        # https://lists.linuxfoundation.org/pipermail/bitcoin-dev/2018-June/016105.html
        # https://lists.linuxfoundation.org/pipermail/bitcoin-dev/attachments/20180609/9f4f5b1f/attachment-0001.pdf
        # https://bitcoin.stackexchange.com/questions/76121/how-is-the-leaf-node-weakness-in-merkle-trees-exploitable/76122#76122
        tx = Transaction(raw_tx)
        try:
            tx.deserialize()
        except:
            pass
        else:
            raise InnerNodeOfSpvProofIsValidTx()

    async def _maybe_undo_verifications(self):
        old_chain = self.blockchain
        cur_chain = self.network.blockchain()
        if cur_chain != old_chain:
            self.blockchain = cur_chain
            above_height = cur_chain.get_height_of_last_common_block_with_chain(old_chain)
            self.logger.info(f"undoing verifications above height {above_height}")
            tx_hashes = self.wallet.undo_verifications(self.blockchain, above_height)
            for tx_hash in tx_hashes:
                self.logger.info(f"redoing {tx_hash}")
                self.remove_spv_proof_for_tx(tx_hash)

    def remove_spv_proof_for_tx(self, tx_hash):
        self.merkle_roots.pop(tx_hash, None)
        self.requested_merkle.discard(tx_hash)

    def is_up_to_date(self):
        return not self.requested_merkle


async def verify_tx_is_in_block(network, tx_hash: str, block_header: Optional[dict],
                            block_height: int):
    """Raise MerkleVerificationFailure if verification fails."""
    if not block_header:
        raise MissingBlockHeader("tx verification failed for {} (missing header {})"
                                    .format(tx_hash, block_height))
    try:
        res = await network.get_transaction(tx_hash, verbose=True)

        block = await network.get_block(res["blockhash"], verbose=True)
    except Exception as e:
        print(e)
        raise
    if block["height"] != block_height or tx_hash not in block["tx"]:
        raise MerkleVerificationFailure("Tx is not in block verify_tx_is_in_block()")
    return block["tx"].index(tx_hash)