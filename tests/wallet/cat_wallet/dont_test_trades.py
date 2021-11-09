import asyncio
from pathlib import Path
from secrets import token_bytes

import pytest

from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.trade_manager import TradeManager
from chia.wallet.trading.trade_status import TradeStatus
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert
from tests.wallet.sync.test_wallet_sync import wallet_height_at_least


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="module")
async def two_wallet_nodes():
    async for _ in setup_simulators_and_wallets(1, 2, {}):
        yield _


buffer_blocks = 4


@pytest.fixture(scope="module")
async def wallets_prefarm(two_wallet_nodes):
    """
    Sets up the node with 10 blocks, and returns a payer and payee wallet.
    """
    farm_blocks = 10
    buffer = 4
    full_nodes, wallets = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, wallet_server_0 = wallets[0]
    wallet_node_1, wallet_server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    ph0 = await wallet_0.get_new_puzzlehash()
    ph1 = await wallet_1.get_new_puzzlehash()

    await wallet_server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await wallet_server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    for i in range(0, farm_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph0))

    for i in range(0, farm_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    for i in range(0, buffer):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

    return wallet_node_0, wallet_node_1, full_node_api


class TestCATTrades:
    @pytest.mark.asyncio
    async def test_cat_trade(self, wallets_prefarm):
        wallet_node_0, wallet_node_1, full_node = wallets_prefarm
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, {"identifier": "genesis_by_id"}, uint64(100)
        )
        await asyncio.sleep(1)

        for i in range(1, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))
        await time_out_assert(15, wallet_height_at_least, True, wallet_node_0, 27)
        await time_out_assert(15, cat_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 100)

        assert cat_wallet.cat_info.my_genesis_checker is not None
        colour = cat_wallet.get_colour()

        cat_wallet_2: CATWallet = await CATWallet.create_wallet_for_cat(
            wallet_node_1.wallet_state_manager, wallet_1, colour
        )
        await asyncio.sleep(1)

        assert cat_wallet.cat_info.my_genesis_checker == cat_wallet_2.cat_info.my_genesis_checker

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))
        await time_out_assert(15, wallet_height_at_least, True, wallet_node_0, 31)
        # send cat_wallet 2 a coin
        cat_hash = await cat_wallet_2.get_new_inner_hash()
        tx_records = await cat_wallet.generate_signed_transaction([uint64(1)], [cat_hash])
        for tx_record in tx_records:
            await wallet_0.wallet_state_manager.add_pending_transaction(tx_record)
            await asyncio.sleep(1)
        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))
        await time_out_assert(15, wallet_height_at_least, True, wallet_node_0, 35)

        trade_manager_0 = wallet_node_0.wallet_state_manager.trade_manager
        trade_manager_1 = wallet_node_1.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        offer_dict = {1: 10, 2: -30}

        success, trade_offer, error = await trade_manager_0.create_offer_for_ids(offer_dict, file)
        await asyncio.sleep(1)

        assert success is True
        assert trade_offer is not None

        success, offer, error = await trade_manager_1.get_discrepancies_for_offer(file_path)
        await asyncio.sleep(1)

        assert error is None
        assert success is True
        assert offer is not None

        assert offer["chia"] == -10
        assert offer[colour] == 30

        success, trade, reason = await trade_manager_1.respond_to_offer(file_path)
        await asyncio.sleep(1)

        assert success is True

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, wallet_height_at_least, True, wallet_node_0, 39)
        await time_out_assert(15, cat_wallet_2.get_confirmed_balance, 31)
        await time_out_assert(15, cat_wallet_2.get_unconfirmed_balance, 31)
        trade_2 = await trade_manager_0.get_trade_by_id(trade_offer.trade_id)
        assert TradeStatus(trade_2.status) is TradeStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_cat_trade_accept_with_zero(self, wallets_prefarm):
        wallet_node_0, wallet_node_1, full_node = wallets_prefarm
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, {"identifier": "genesis_by_id"}, uint64(100)
        )
        await asyncio.sleep(1)

        for i in range(1, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 100)

        assert cat_wallet.cat_info.my_genesis_checker is not None
        colour = cat_wallet.get_colour()

        cat_wallet_2: CATWallet = await CATWallet.create_wallet_for_cat(
            wallet_node_1.wallet_state_manager, wallet_1, colour
        )
        await asyncio.sleep(1)

        assert cat_wallet.cat_info.my_genesis_checker == cat_wallet_2.cat_info.my_genesis_checker

        ph = await wallet_1.get_new_puzzlehash()
        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        trade_manager_0 = wallet_node_0.wallet_state_manager.trade_manager
        trade_manager_1 = wallet_node_1.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        offer_dict = {1: 10, 3: -30}

        success, trade_offer, error = await trade_manager_0.create_offer_for_ids(offer_dict, file)
        await asyncio.sleep(1)

        assert success is True
        assert trade_offer is not None

        success, offer, error = await trade_manager_1.get_discrepancies_for_offer(file_path)
        await asyncio.sleep(1)

        assert error is None
        assert success is True
        assert offer is not None

        assert cat_wallet.get_colour() == cat_wallet_2.get_colour()

        assert offer["chia"] == -10
        assert offer[colour] == 30

        success, trade, reason = await trade_manager_1.respond_to_offer(file_path)
        await asyncio.sleep(1)

        assert success is True

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cat_wallet_2.get_confirmed_balance, 30)
        await time_out_assert(15, cat_wallet_2.get_unconfirmed_balance, 30)
        trade_2 = await trade_manager_0.get_trade_by_id(trade_offer.trade_id)
        assert TradeStatus(trade_2.status) is TradeStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_cat_trade_with_multiple_colours(self, wallets_prefarm):
        # This test start with CATWallet in both wallets. wall
        # wallet1 {wallet_id: 2 = 70}
        # wallet2 {wallet_id: 2 = 30}

        wallet_node_a, wallet_node_b, full_node = wallets_prefarm
        wallet_a = wallet_node_a.wallet_state_manager.main_wallet
        wallet_b = wallet_node_b.wallet_state_manager.main_wallet

        # cat_a_2 = coloured coin, Alice, wallet id = 2
        cat_a_2 = wallet_node_a.wallet_state_manager.wallets[2]
        cat_b_2 = wallet_node_b.wallet_state_manager.wallets[2]

        cat_a_3: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_a.wallet_state_manager, wallet_a, {"identifier": "genesis_by_id"}, uint64(100)
        )
        await asyncio.sleep(1)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cat_a_3.get_confirmed_balance, 100)
        await time_out_assert(15, cat_a_3.get_unconfirmed_balance, 100)

        # store these for asserting change later
        cat_balance = await cat_a_2.get_unconfirmed_balance()
        cat_balance_2 = await cat_b_2.get_unconfirmed_balance()

        assert cat_a_3.cat_info.my_genesis_checker is not None
        red = cat_a_3.get_colour()

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        cat_b_3: CATWallet = await CATWallet.create_wallet_for_cat(wallet_node_b.wallet_state_manager, wallet_b, red)
        await asyncio.sleep(1)

        assert cat_a_3.cat_info.my_genesis_checker == cat_b_3.cat_info.my_genesis_checker

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        trade_manager_0 = wallet_node_a.wallet_state_manager.trade_manager
        trade_manager_1 = wallet_node_b.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        # Wallet
        offer_dict = {1: 1000, 2: -20, 4: -50}

        success, trade_offer, error = await trade_manager_0.create_offer_for_ids(offer_dict, file)
        await asyncio.sleep(1)

        assert success is True
        assert trade_offer is not None

        success, offer, error = await trade_manager_1.get_discrepancies_for_offer(file_path)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert offer is not None
        assert offer["chia"] == -1000

        colour_2 = cat_a_2.get_colour()
        colour_3 = cat_a_3.get_colour()

        assert offer[colour_2] == 20
        assert offer[colour_3] == 50

        success, trade, reason = await trade_manager_1.respond_to_offer(file_path)
        await asyncio.sleep(1)

        assert success is True
        for i in range(0, 10):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cat_b_3.get_confirmed_balance, 50)
        await time_out_assert(15, cat_b_3.get_unconfirmed_balance, 50)

        await time_out_assert(15, cat_a_3.get_confirmed_balance, 50)
        await time_out_assert(15, cat_a_3.get_unconfirmed_balance, 50)

        await time_out_assert(15, cat_a_2.get_unconfirmed_balance, cat_balance - offer[colour_2])
        await time_out_assert(15, cat_b_2.get_unconfirmed_balance, cat_balance_2 + offer[colour_2])

        trade = await trade_manager_0.get_trade_by_id(trade_offer.trade_id)

        status: TradeStatus = TradeStatus(trade.status)

        assert status is TradeStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_create_offer_with_zero_val(self, wallets_prefarm):
        # Wallet A              Wallet B
        # CATWallet id 2: 50     CATWallet id 2: 50
        # CATWallet id 3: 50     CATWallet id 2: 50
        # Wallet A will
        # Wallet A will create a new CAT and wallet B will create offer to buy that coin

        wallet_node_a, wallet_node_b, full_node = wallets_prefarm
        wallet_a = wallet_node_a.wallet_state_manager.main_wallet
        wallet_b = wallet_node_b.wallet_state_manager.main_wallet
        trade_manager_a: TradeManager = wallet_node_a.wallet_state_manager.trade_manager
        trade_manager_b: TradeManager = wallet_node_b.wallet_state_manager.trade_manager

        cat_a_4: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_a.wallet_state_manager, wallet_a, {"identifier": "genesis_by_id"}, uint64(100)
        )
        await asyncio.sleep(1)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cat_a_4.get_confirmed_balance, 100)

        colour = cat_a_4.get_colour()

        cat_b_4: CATWallet = await CATWallet.create_wallet_for_cat(wallet_node_b.wallet_state_manager, wallet_b, colour)
        cat_balance = await cat_a_4.get_confirmed_balance()
        cat_balance_2 = await cat_b_4.get_confirmed_balance()
        offer_dict = {1: -30, cat_a_4.id(): 50}

        file = "test_offer_file.offer"
        file_path = Path(file)
        if file_path.exists():
            file_path.unlink()

        success, offer, error = await trade_manager_b.create_offer_for_ids(offer_dict, file)

        success, trade_a, reason = await trade_manager_a.respond_to_offer(file_path)
        await asyncio.sleep(1)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))
        await time_out_assert(15, cat_a_4.get_confirmed_balance, cat_balance - 50)
        await time_out_assert(15, cat_b_4.get_confirmed_balance, cat_balance_2 + 50)

        async def assert_func():
            assert trade_a is not None
            trade = await trade_manager_a.get_trade_by_id(trade_a.trade_id)
            assert trade is not None
            return trade.status

        async def assert_func_b():
            assert offer is not None
            trade = await trade_manager_b.get_trade_by_id(offer.trade_id)
            assert trade is not None
            return trade.status

        await time_out_assert(15, assert_func, TradeStatus.CONFIRMED.value)
        await time_out_assert(15, assert_func_b, TradeStatus.CONFIRMED.value)

    @pytest.mark.asyncio
    async def test_cat_trade_cancel_insecure(self, wallets_prefarm):
        # Wallet A              Wallet B
        # CATWallet id 2: 50     CATWallet id 2: 50
        # CATWallet id 3: 50     CATWallet id 3: 50
        # CATWallet id 4: 40     CATWallet id 4: 60
        # Wallet A will create offer, cancel it by deleting from db only
        wallet_node_a, wallet_node_b, full_node = wallets_prefarm
        wallet_a = wallet_node_a.wallet_state_manager.main_wallet
        trade_manager_a: TradeManager = wallet_node_a.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        spendable_chia = await wallet_a.get_spendable_balance()

        offer_dict = {1: 10, 2: -30, 3: 30}

        success, trade_offer, error = await trade_manager_a.create_offer_for_ids(offer_dict, file)
        await asyncio.sleep(1)

        spendable_chia_after = await wallet_a.get_spendable_balance()

        locked_coin = await trade_manager_a.get_locked_coins(wallet_a.id())
        locked_sum = 0
        for name, record in locked_coin.items():
            locked_sum += record.coin.amount

        assert spendable_chia == spendable_chia_after + locked_sum
        assert success is True
        assert trade_offer is not None

        # Cancel offer 1 by just deleting from db
        await trade_manager_a.cancel_pending_offer(trade_offer.trade_id)
        await asyncio.sleep(1)
        spendable_after_cancel_1 = await wallet_a.get_spendable_balance()

        # Spendable should be the same as it was before making offer 1
        assert spendable_chia == spendable_after_cancel_1

        trade_a = await trade_manager_a.get_trade_by_id(trade_offer.trade_id)
        assert trade_a is not None
        assert trade_a.status == TradeStatus.CANCELED.value

    @pytest.mark.asyncio
    async def test_cat_trade_cancel_secure(self, wallets_prefarm):
        # Wallet A              Wallet B
        # CATWallet id 2: 50     CATWallet id 2: 50
        # CATWallet id 3: 50     CATWallet id 3: 50
        # CATWallet id 4: 40     CATWallet id 4: 60
        # Wallet A will create offer, cancel it by spending coins back to self

        wallet_node_a, wallet_node_b, full_node = wallets_prefarm
        wallet_a = wallet_node_a.wallet_state_manager.main_wallet
        trade_manager_a: TradeManager = wallet_node_a.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        spendable_chia = await wallet_a.get_spendable_balance()

        offer_dict = {1: 10, 2: -30, 3: 30}

        success, trade_offer, error = await trade_manager_a.create_offer_for_ids(offer_dict, file)
        await asyncio.sleep(1)

        spendable_chia_after = await wallet_a.get_spendable_balance()

        locked_coin = await trade_manager_a.get_locked_coins(wallet_a.id())
        locked_sum = 0
        for name, record in locked_coin.items():
            locked_sum += record.coin.amount

        assert spendable_chia == spendable_chia_after + locked_sum
        assert success is True
        assert trade_offer is not None

        # Cancel offer 1 by spending coins that were offered
        await trade_manager_a.cancel_pending_offer_safely(trade_offer.trade_id)
        await asyncio.sleep(1)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, wallet_a.get_spendable_balance, spendable_chia)

        # Spendable should be the same as it was before making offer 1

        async def get_status():
            assert trade_offer is not None
            trade_a = await trade_manager_a.get_trade_by_id(trade_offer.trade_id)
            assert trade_a is not None
            return trade_a.status

        await time_out_assert(15, get_status, TradeStatus.CANCELED.value)
