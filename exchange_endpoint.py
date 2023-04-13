from flask import Flask, request, g
from flask_restful import Resource, Api
from sqlalchemy import create_engine
from flask import jsonify
import json
import eth_account
import algosdk
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import scoped_session
from sqlalchemy.orm import load_only
from datetime import datetime
import math
import sys
import traceback
from web3 import Web3
from eth_account import Account

# TODO: make sure you implement connect_to_algo, send_tokens_algo, and send_tokens_eth
from send_tokens import connect_to_algo, connect_to_eth, send_tokens_algo, send_tokens_eth

from models import Base, Order, TX, Log

engine = create_engine('sqlite:///orders.db')
Base.metadata.bind = engine
DBSession = sessionmaker(bind=engine)

app = Flask(__name__)

""" Pre-defined methods (do not need to change) """


@app.before_request
def create_session():
    g.session = scoped_session(DBSession)


@app.teardown_appcontext
def shutdown_session(response_or_exc):
    sys.stdout.flush()
    g.session.commit()
    g.session.remove()


def connect_to_blockchains():
    try:
        # If g.acl has not been defined yet, then trying to query it fails
        acl_flag = False
        g.acl
    except AttributeError as ae:
        acl_flag = True

    try:
        if acl_flag or not g.acl.status():
            # Define Algorand client for the application
            g.acl = connect_to_algo()
    except Exception as e:
        print("Trying to connect to algorand client again")
        print(traceback.format_exc())
        g.acl = connect_to_algo()

    try:
        icl_flag = False
        g.icl
    except AttributeError as ae:
        icl_flag = True

    try:
        if icl_flag or not g.icl.health():
            # Define the index client
            g.icl = connect_to_algo(connection_type='indexer')
    except Exception as e:
        print("Trying to connect to algorand indexer client again")
        print(traceback.format_exc())
        g.icl = connect_to_algo(connection_type='indexer')

    try:
        w3_flag = False
        g.w3
    except AttributeError as ae:
        w3_flag = True

    try:
        if w3_flag or not g.w3.isConnected():
            g.w3 = connect_to_eth()
    except Exception as e:
        print("Trying to connect to web3 again")
        print(traceback.format_exc())
        g.w3 = connect_to_eth()


""" End of pre-defined methods """

""" Helper Methods (skeleton code for you to implement) """


def log_message(message_dict):
    msg = json.dumps(message_dict)

    # TODO: Add message to the Log table
    log_entry = Log(msg)
    g.session.add(log_entry)
    g.session.commit()
    return




def is_signature_valid(payload, sig, platform):
    if platform == 'Algorand':
        alg_encoded_msg = json.dumps(payload).encode('utf-8')
        verify = (algosdk.util.verify_bytes(alg_encoded_msg, sig, payload['sender_pk']))
        return verify
    elif platform == 'Ethereum':
        eth_encoded_msg = eth_account.messages.encode_defunct(text=json.dumps(payload))
        signer_pk = eth_account.Account.recover_message(eth_encoded_msg, signature=sig)
        verify = (signer_pk == payload['sender_pk'])
        return verify
    else:
        verify = False
        return verify


def get_algo_keys():
    # TODO: Generate or read (using the mnemonic secret)
    # the algorand public/private keys
    mnemonic_secret = "original crisp season bike anchor live punch survey reject egg wink moon obvious paddle hazard engage elephant chunk panther violin daughter hen genre ability alarm"
    algo_sk= algosdk.mnemonic.to_private_key(mnemonic_secret)
    algo_pk = algosdk.mnemonic.to_public_key(mnemonic_secret)

    return algo_sk, algo_pk


def get_eth_keys(filename="eth_mnemonic.txt"):
    print("Test Print", file=sys.stderr)
    w3 = Web3()

    # TODO: Generate or read (using the mnemonic secret)
    # the ethereum public/private keys
    #with open(filename, "r") as f:
    #    mnemonic_secret = f.read().strip()

    mnemonic_secret = 'garden faint wink child monster remove mirror advice choice screen luxury monkey'

    #acct = Account.from_mnemonic(mnemonic_secret)
    #acct = w3.eth.account.from_mnemonic(mnemonic_secret)
    #eth_sk = acct.privateKey #.hex()
    #eth_pk = acct.address
    eth_sk = b's\xd2\x9e\xa2\xab\xef\xadVE\xf7u\xd8@D#\xdf;kx\xce\r\x8f\xafW\xfe\xfcLV{\xf8{\xdb'
    eth_pk = 0x643fe40726645A47f16541C993Be9C4f73FD8F25

    return eth_sk, eth_pk


def fill_order(order, txes=[]):
    # TODO:
    # Match orders (same as Exchange Server II)
    # Validate the order has a payment to back it (make sure the counterparty also made a payment)
    # Make sure that you end up executing all resulting transactions!
    new_order = Order(
        buy_currency=order['buy_currency'],
        sell_currency=order['sell_currency'],
        buy_amount=order['buy_amount'],
        sell_amount=order['sell_amount'],
        sender_pk=order['sender_pk'],
        receiver_pk=order['receiver_pk']
    )


    g.session.add(new_order)
    g.session.commit()

    orders_iterate = g.session.query(Order).filter(
        Order.filled.is_(None),
        Order.buy_currency == new_order.sell_currency,
        Order.sell_currency == new_order.buy_currency,
        ((Order.sell_amount / Order.buy_amount) >= (new_order.buy_amount / new_order.sell_amount)),
        ((Order.sell_amount * new_order.sell_amount) >= (Order.buy_amount * new_order.buy_amount)),
    ).all()

    for existing_order in orders_iterate:
        if existing_order.filled is not None or new_order.filled is not None:
            continue

        time = datetime.now()
        new_order.filled = time
        existing_order.filled = time

        new_order.counterparty_id = existing_order.id
        existing_order.counterparty_id = new_order.id

        g.session.commit()

        if new_order.sell_amount < existing_order.buy_amount:
            left_over_buy_amount = existing_order.buy_amount - new_order.sell_amount
            left_over_sell_amount = left_over_buy_amount * (existing_order.sell_amount / existing_order.buy_amount)

            child_order = {
                'buy_currency': existing_order.buy_currency,
                'sell_currency': existing_order.sell_currency,
                'buy_amount': left_over_buy_amount,
                'sell_amount': left_over_sell_amount,
                'sender_pk': existing_order.sender_pk,
                'receiver_pk': existing_order.receiver_pk,
                'creator_id': existing_order.id
            }
            child_order_obj = Order(buy_currency=child_order['buy_currency'],
                                    sell_currency=child_order['sell_currency'],
                                    buy_amount=child_order['buy_amount'],
                                    sell_amount=child_order['sell_amount'],
                                    sender_pk=child_order['sender_pk'],
                                    receiver_pk=child_order['receiver_pk'],
                                    creator_id=child_order['creator_id']
                                    )

            g.session.add(child_order_obj)
            g.session.commit()


        elif new_order.buy_amount > existing_order.sell_amount:
            left_over_buy_amount = new_order.buy_amount - existing_order.sell_amount
            left_over_sell_amount = left_over_buy_amount * (new_order.sell_amount / new_order.buy_amount)

            child_order = {
                'buy_currency': new_order.buy_currency,
                'sell_currency': new_order.sell_currency,
                'buy_amount': left_over_buy_amount,
                'sell_amount': left_over_sell_amount,
                'sender_pk': new_order.sender_pk,
                'receiver_pk': new_order.receiver_pk,
                'creator_id': new_order.id

            }
            child_order_obj = Order(buy_currency=child_order['buy_currency'],
                                    sell_currency=child_order['sell_currency'],
                                    buy_amount=child_order['buy_amount'],
                                    sell_amount=child_order['sell_amount'],
                                    sender_pk=child_order['sender_pk'],
                                    receiver_pk=child_order['receiver_pk'],
                                    creator_id = child_order['creator_id']
                                    )
            g.session.add(child_order_obj)
            g.session.commit()
            break
    for tx in txes:
        fill_order(tx)
    pass


def execute_txes(txes):
    if txes is None:
        return True
    if len(txes) == 0:
        return True
    print(f"Trying to execute {len(txes)} transactions")
    print(f"IDs = {[tx['order_id'] for tx in txes]}")
    eth_sk, eth_pk = get_eth_keys()
    algo_sk, algo_pk = get_algo_keys()

    if not all(tx['platform'] in ["Algorand", "Ethereum"] for tx in txes):
        print("Error: execute_txes got an invalid platform!")
        print(tx['platform'] for tx in txes)

    algo_txes = [tx for tx in txes if tx['platform'] == "Algorand"]
    eth_txes = [tx for tx in txes if tx['platform'] == "Ethereum"]

    # TODO:
    #       1. Send tokens on the Algorand and eth testnets, appropriately
    #          We've provided the send_tokens_algo and send_tokens_eth skeleton methods in send_tokens_old.py
    #       2. Add all transactions to the TX table


    for tx in algo_txes:
        result = send_tokens_algo(algo_sk, tx.receiver_pk, tx.sell_amount)
        if result==True:
            # Add the transaction to the TX table
            new_tx = TX(
                platform=tx.platform,
                receiver_pk=tx.receiver_pk,
                order_id=tx.order_id,
                tx_id=tx.id
            )
            g.session.add(new_tx)
            g.session.commit()
        else:
            print(f"Failed to execute transaction for order {tx.id}")
    for tx in eth_txes:
        result = send_tokens_eth(eth_sk, tx.receiver_pk, tx.sell_amount)
        if result==True:
            new_tx = TX(
                platform=tx.platform,
                receiver_pk=tx.receiver_pk,
                order_id=tx.order_id,
                tx_id=tx.id
            )
            g.session.add(new_tx)
            g.session.commit()
        else:
           print(f"Failed to execute transaction for order {tx.id}")

    pass


""" End of Helper methods"""


@app.route('/address', methods=['POST'])
def address():
    print("Test Print", file=sys.stderr)
    if request.method == "POST":
        content = request.get_json(silent=True)
        if 'platform' not in content.keys():
            print(f"Error: no platform provided")
            return jsonify("Error: no platform provided")
        if not content['platform'] in ["Ethereum", "Algorand"]:
            print(f"Error: {content['platform']} is an invalid platform")
            return jsonify(f"Error: invalid platform provided: {content['platform']}")

        if content['platform'] == "Ethereum":
            # Your code here'
            #eth_sk, eth_pk = get_eth_keys()
            #return jsonify({"public_key": eth_pk})

            eth_sk, eth_pk = get_eth_keys()
            """
            try:
            # Breaking code goes here
                eth_sk, eth_pk = get_eth_keys()
                return jsonify(eth_pk)
            except Exception as e:
                import traceback
                print(traceback.format_exc())
                print(e)
            """
            return jsonify(eth_pk)
        if content['platform'] == "Algorand":
            # Your code here
            alg_sk, alg_pk = get_algo_keys()
            return jsonify(alg_pk)
            #return jsonify({"public_key": alg_pk})


@app.route('/trade', methods=['POST'])
def trade():
    print("In trade", file=sys.stderr)
    connect_to_blockchains()
    get_keys()
    if request.method == "POST":
        content = request.get_json(silent=True)
        columns = ["buy_currency", "sell_currency", "buy_amount", "sell_amount", "platform", "tx_id", "receiver_pk"]
        fields = ["sig", "payload"]
        error = False
        for field in fields:
            if not field in content.keys():
                print(f"{field} not received by Trade")
                error = True
        if error:
            print(json.dumps(content))
            return jsonify(False)

        error = False
        for column in columns:
            if not column in content['payload'].keys():
                print(f"{column} not received by Trade")
                error = True
        if error:
            print(json.dumps(content))
            return jsonify(False)

        # Your code here

        # 1. Check the signature

        # 2. Add the order to the table

        # 3a. Check if the order is backed by a transaction equal to the sell_amount (this is new)

        # 3b. Fill the order (as in Exchange Server II) if the order is valid

        # 4. Execute the transactions

        # If all goes well, return jsonify(True). else return jsonify(False)

        content = request.get_json(silent=True)
        payload = content['payload']
        sig = content['sig']
        platform = payload['platform']
        if platform == "Algorand":
            algo_sk, algo_pk = get_algo_keys()
        elif platform == "Ethereum":
            eth_sk, eth_pk = get_eth_keys()
        valid_signature = is_signature_valid(payload, sig, platform)
        if valid_signature == True:
            new_order = Order(
                order_id=payload['tx_id'],
                buy_currency=payload['buy_currency'],
                sell_currency=payload['sell_currency'],
                buy_amount=payload['buy_amount'],
                sell_amount=payload['sell_amount'],
                sender_pk=algo_pk if platform == "Algorand" else eth_pk,
                receiver_pk=payload['receiver_pk'],
                platform=platform,
                tx_id = payload['tx_id']

            )
            equal_sell_amount = False
            if platform == "Algorand":
                transactions = g.icl.search_transactions(address=new_order.sender_pk, asset_id=int(new_order.sell_currency))
                for tx in transactions:
                    if tx['payment']['amount'] == new_order.sell_amount:
                        equal_sell_amount= True
            elif platform == "Ethereum":
                transactions = g.w3.eth.getBalance(new_order.sender_pk)
                #transactions = w3.eth.get_transaction(new_order.tx_id)
                for tx in transactions:
                    if tx['value'] == new_order.sell_amount:
                        equal_sell_amount= True
            if equal_sell_amount == False:
                result = jsonify(False)
                return result
            g.session.add(new_order)
            g.session.commit()
            result = jsonify(True)
            return result
        else:
            log_message(payload)
            result = jsonify(False)
            return result

        return jsonify(True)


@app.route('/order_book')
def order_book():
    # Same as before
    all_orders = g.session.query(Order).all()
    result = {'data': []}
    for o in all_orders:
        order_data = {
            'sender_pk': o.sender_pk,
            'receiver_pk': o.receiver_pk,
            'buy_currency': o.buy_currency,
            'sell_currency': o.sell_currency,
            'buy_amount': o.buy_amount,
            'sell_amount': o.sell_amount,
            'signature': o.signature, #potentially remove me
            'tx_id': o.tx_id
        }
        result['data'].append(order_data)

    return jsonify(result)


if __name__ == '__main__':
    app.run(port='5002')