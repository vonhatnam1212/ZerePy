import logging
import os
import time
import requests
from typing import Dict, Any, Optional, Union
from dotenv import load_dotenv, set_key
from web3 import Web3
from web3.middleware import geth_poa_middleware
from src.constants.networks import EVM_NETWORKS
from src.constants.abi import ERC20_ABI
from src.connections.base_connection import BaseConnection, Action, ActionParameter
import json


logger = logging.getLogger("connections.evm_connection")


class EVMConnectionError(Exception):
    """Base exception for EVM connection errors"""
    pass


class EVMConnection(BaseConnection):
    def __init__(self, config: Dict[str, Any]):
        logger.info("Initializing EVM connection...")
        self.NATIVE_TOKEN = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

        # Determine network from config (defaulting to 'ethereum')
        self._web3 = None
        self.network = config.get("network", "ethereum")
        if self.network not in EVM_NETWORKS:
            raise ValueError(
                f"Invalid network '{self.network}'. Must be one of: {', '.join(EVM_NETWORKS.keys())}"
            )
        network_config = EVM_NETWORKS[self.network]

        # Get RPC URL: either from the config override or from the network defaults
        self.rpc_url = config.get("rpc") or network_config["rpc_url"]
        self.scanner_url = network_config["scanner_url"]
        self.chain_id = network_config["chain_id"]

        super().__init__(config)
        self._initialize_web3()

        # Kyberswap aggregator API for best swap routes
        self.aggregator_api = f"https://aggregator-api.kyberswap.com/{self.network}/api/v1"

    def _get_explorer_link(self, tx_hash: str) -> str:
        """Generate block explorer link for transaction"""
        return f"https://{self.scanner_url}/tx/{tx_hash}"

    def _initialize_web3(self) -> None:
        """Initialize Web3 connection with retry logic"""
        if not self._web3:
            for attempt in range(3):
                try:
                    self._web3 = Web3(Web3.HTTPProvider(self.rpc_url))
                    self._web3.middleware_onion.inject(
                        geth_poa_middleware, layer=0)
                    logger.info(
                        f"Connected to {self.network} network with chain ID: {self.chain_id}")
                    break
                except Exception as e:
                    if attempt == 2:
                        raise Exception(
                            f"Failed to initialize Web3 after 3 attempts: {str(e)}")
                    logger.warning(
                        f"Web3 initialization attempt {attempt + 1} failed: {str(e)}")
                    time.sleep(1)

    @property
    def is_llm_provider(self) -> bool:
        return False

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Ethereum configuration from JSON"""
        if "rpc" not in config and "network" not in config:
            raise ValueError("Config must contain either 'rpc' or 'network'")
        if "network" in config and config["network"] not in EVM_NETWORKS:
            raise ValueError(
                f"Invalid network '{config['network']}'. Must be one of: {', '.join(EVM_NETWORKS.keys())}")
        return config

    def register_actions(self) -> None:
        """Register available Ethereum actions"""
        self.actions = {
            "get-token-by-ticker": Action(
                name="get-token-by-ticker",
                parameters=[
                    ActionParameter("ticker", True, str,
                                    "Token ticker symbol to look up")
                ],
                description="Get token address by ticker symbol"
            ),
            "get-balance": Action(
                name="get-balance",
                parameters=[
                    ActionParameter(
                        "token_address", False, str, "Token address (optional, native token if not provided)")
                ],
                description="Get ETH or token balance"
            ),
            "transfer": Action(
                name="transfer",
                parameters=[
                    ActionParameter("to_address", True, str,
                                    "Recipient address"),
                    ActionParameter("amount", True, float,
                                    "Amount to transfer"),
                    ActionParameter(
                        "token_address", False, str, "Token address (optional, native token if not provided)")
                ],
                description="Send ETH or tokens"
            ),
            "get-address": Action(
                name="get-address",
                parameters=[],
                description="Get your Ethereum wallet address"
            ),
            "deploy-erc": Action(
                name="deploy-erc",
                parameters=[
                    ActionParameter("name", True, str, "Token name"),
                    ActionParameter("symbol", True, str, "Token symbol"),
                    ActionParameter("supply", True, float, "Token supply")
                ],
                description="Deploy your token"
            ),
            "swap": Action(
                name="swap",
                parameters=[
                    ActionParameter("token_in", True, str,
                                    "Input token address"),
                    ActionParameter("token_out", True, str,
                                    "Output token address"),
                    ActionParameter("amount", True, float, "Amount to swap"),
                    ActionParameter("slippage", False, float,
                                    "Max slippage percentage (default 0.5%)")
                ],
                description="Swap tokens using Kyberswap aggregator"
            )
        }

    def configure(self) -> bool:
        """Sets up Ethereum wallet and API credentials"""
        logger.info("\n⛓️ ETHEREUM SETUP")

        if self.is_configured():
            logger.info("Ethereum connection is already configured")
            response = input("Do you want to reconfigure? (y/n): ")
            if response.lower() != 'y':
                return True

        try:
            if not os.path.exists('.env'):
                with open('.env', 'w') as f:
                    f.write('')

            # Get wallet private key from user input
            private_key = input("\nEnter your wallet private key: ")
            if not private_key.startswith('0x'):
                private_key = '0x' + private_key

            # Validate private key format
            if len(private_key) != 66 or not all(c in '0123456789abcdefABCDEF' for c in private_key[2:]):
                raise ValueError("Invalid private key format")

            # Test private key by deriving address
            account = self._web3.eth.account.from_key(private_key)
            logger.info(f"\nDerived address: {account.address}")

            # Optional block explorer API key input
            explorer_key = input(
                "\nEnter your block explorer API key (optional, press Enter to skip): ")

            # Save credentials using the unified EVM_PRIVATE_KEY variable
            set_key('.env', 'EVM_PRIVATE_KEY', private_key)
            if explorer_key:
                set_key('.env', 'ETH_EXPLORER_KEY', explorer_key)

            logger.info("\n✅ Ethereum configuration saved successfully!")
            return True

        except Exception as e:
            logger.error(f"Configuration failed: {str(e)}")
            return False

    def is_configured(self, verbose: bool = False) -> bool:
        """Check if Ethereum connection is properly configured"""
        try:
            load_dotenv()
            private_key = os.getenv(
                'EVM_PRIVATE_KEY') or os.getenv('ETH_PRIVATE_KEY')
            if not private_key:
                if verbose:
                    logger.error(
                        "Missing EVM_PRIVATE_KEY or ETH_PRIVATE_KEY in .env")
                return False

            if not self._web3 or not self._web3.is_connected():
                if verbose:
                    logger.error("Not connected to Ethereum network")
                return False

            # Test account access
            account = self._web3.eth.account.from_key(private_key)
            _ = self._web3.eth.get_balance(account.address)
            return True

        except Exception as e:
            if verbose:
                logger.error(f"Configuration check failed: {str(e)}")
            return False

    def deploy_erc(self, name, symbol, supply) -> str:
        private_key = os.getenv(
            'EVM_PRIVATE_KEY') or os.getenv('ETH_PRIVATE_KEY')
        account = self._web3.eth.account.from_key(private_key)
        with open('./src/connections/abi.json', 'r') as file:
            abi = json.load(file)

        bytecode = "60806040523480156200001157600080fd5b5060405162001f2e38038062001f2e833981810160405281019062000037919062000361565b836000908162000048919062000652565b5082600190816200005a919062000652565b5081600260006101000a81548160ff021916908360ff1602179055508160ff16600a620000889190620008bc565b816200009591906200090d565b600381905550600354600460003373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff168152602001908152602001600020819055503373ffffffffffffffffffffffffffffffffffffffff16600073ffffffffffffffffffffffffffffffffffffffff167fddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef60035460405162000143919062000969565b60405180910390a35050505062000986565b6000604051905090565b600080fd5b600080fd5b600080fd5b600080fd5b6000601f19601f8301169050919050565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052604160045260246000fd5b620001be8262000173565b810181811067ffffffffffffffff82111715620001e057620001df62000184565b5b80604052505050565b6000620001f562000155565b9050620002038282620001b3565b919050565b600067ffffffffffffffff82111562000226576200022562000184565b5b620002318262000173565b9050602081019050919050565b60005b838110156200025e57808201518184015260208101905062000241565b60008484015250505050565b6000620002816200027b8462000208565b620001e9565b905082815260208101848484011115620002a0576200029f6200016e565b5b620002ad8482856200023e565b509392505050565b600082601f830112620002cd57620002cc62000169565b5b8151620002df8482602086016200026a565b91505092915050565b600060ff82169050919050565b6200030081620002e8565b81146200030c57600080fd5b50565b6000815190506200032081620002f5565b92915050565b6000819050919050565b6200033b8162000326565b81146200034757600080fd5b50565b6000815190506200035b8162000330565b92915050565b600080600080608085870312156200037e576200037d6200015f565b5b600085015167ffffffffffffffff8111156200039f576200039e62000164565b5b620003ad87828801620002b5565b945050602085015167ffffffffffffffff811115620003d157620003d062000164565b5b620003df87828801620002b5565b9350506040620003f2878288016200030f565b925050606062000405878288016200034a565b91505092959194509250565b600081519050919050565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052602260045260246000fd5b600060028204905060018216806200046457607f821691505b6020821081036200047a57620004796200041c565b5b50919050565b60008190508160005260206000209050919050565b60006020601f8301049050919050565b600082821b905092915050565b600060088302620004e47fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff82620004a5565b620004f08683620004a5565b95508019841693508086168417925050509392505050565b6000819050919050565b6000620005336200052d620005278462000326565b62000508565b62000326565b9050919050565b6000819050919050565b6200054f8362000512565b620005676200055e826200053a565b848454620004b2565b825550505050565b600090565b6200057e6200056f565b6200058b81848462000544565b505050565b5b81811015620005b357620005a760008262000574565b60018101905062000591565b5050565b601f8211156200060257620005cc8162000480565b620005d78462000495565b81016020851015620005e7578190505b620005ff620005f68562000495565b83018262000590565b50505b505050565b600082821c905092915050565b6000620006276000198460080262000607565b1980831691505092915050565b600062000642838362000614565b9150826002028217905092915050565b6200065d8262000411565b67ffffffffffffffff81111562000679576200067862000184565b5b6200068582546200044b565b62000692828285620005b7565b600060209050601f831160018114620006ca5760008415620006b5578287015190505b620006c1858262000634565b86555062000731565b601f198416620006da8662000480565b60005b828110156200070457848901518255600182019150602085019450602081019050620006dd565b8683101562000724578489015162000720601f89168262000614565b8355505b6001600288020188555050505b505050505050565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601160045260246000fd5b60008160011c9050919050565b6000808291508390505b6001851115620007c7578086048111156200079f576200079e62000739565b5b6001851615620007af5780820291505b8081029050620007bf8562000768565b94506200077f565b94509492505050565b600082620007e25760019050620008b5565b81620007f25760009050620008b5565b81600181146200080b576002811462000816576200084c565b6001915050620008b5565b60ff8411156200082b576200082a62000739565b5b8360020a91508482111562000845576200084462000739565b5b50620008b5565b5060208310610133831016604e8410600b8410161715620008865782820a90508381111562000880576200087f62000739565b5b620008b5565b62000895848484600162000775565b92509050818404811115620008af57620008ae62000739565b5b81810290505b9392505050565b6000620008c98262000326565b9150620008d68362000326565b9250620009057fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8484620007d0565b905092915050565b60006200091a8262000326565b9150620009278362000326565b9250828202620009378162000326565b9150828204841483151762000951576200095062000739565b5b5092915050565b620009638162000326565b82525050565b600060208201905062000980600083018462000958565b92915050565b61159880620009966000396000f3fe608060405234801561001057600080fd5b50600436106100a95760003560e01c806340c10f191161007157806340c10f191461016857806342966c681461019857806370a08231146101c857806395d89b41146101f8578063a9059cbb14610216578063dd62ed3e14610246576100a9565b806306fdde03146100ae578063095ea7b3146100cc57806318160ddd146100fc57806323b872dd1461011a578063313ce5671461014a575b600080fd5b6100b6610276565b6040516100c39190610ef8565b60405180910390f35b6100e660048036038101906100e19190610fb3565b610304565b6040516100f3919061100e565b60405180910390f35b610104610464565b6040516101119190611038565b60405180910390f35b610134600480360381019061012f9190611053565b61046a565b604051610141919061100e565b60405180910390f35b610152610839565b60405161015f91906110c2565b60405180910390f35b610182600480360381019061017d9190610fb3565b61084c565b60405161018f919061100e565b60405180910390f35b6101b260048036038101906101ad91906110dd565b61099b565b6040516101bf919061100e565b60405180910390f35b6101e260048036038101906101dd919061110a565b610afd565b6040516101ef9190611038565b60405180910390f35b610200610b46565b60405161020d9190610ef8565b60405180910390f35b610230600480360381019061022b9190610fb3565b610bd4565b60405161023d919061100e565b60405180910390f35b610260600480360381019061025b9190611137565b610de1565b60405161026d9190611038565b60405180910390f35b60008054610283906111a6565b80601f01602080910402602001604051908101604052809291908181526020018280546102af906111a6565b80156102fc5780601f106102d1576101008083540402835291602001916102fc565b820191906000526020600020905b8154815290600101906020018083116102df57829003601f168201915b505050505081565b60008073ffffffffffffffffffffffffffffffffffffffff168373ffffffffffffffffffffffffffffffffffffffff1603610374576040517f08c379a000000000000000000000000000000000000000000000000000000000815260040161036b90611223565b60405180910390fd5b81600560003373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002060008573ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff168152602001908152602001600020819055508273ffffffffffffffffffffffffffffffffffffffff163373ffffffffffffffffffffffffffffffffffffffff167f8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925846040516104529190611038565b60405180910390a36001905092915050565b60035481565b60008073ffffffffffffffffffffffffffffffffffffffff168473ffffffffffffffffffffffffffffffffffffffff16036104da576040517f08c379a00000000000000000000000000000000000000000000000000000000081526004016104d19061128f565b60405180910390fd5b600073ffffffffffffffffffffffffffffffffffffffff168373ffffffffffffffffffffffffffffffffffffffff1603610549576040517f08c379a0000000000000000000000000000000000000000000000000000000008152600401610540906112fb565b60405180910390fd5b81600460008673ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020016000205410156105cb576040517f08c379a00000000000000000000000000000000000000000000000000000000081526004016105c290611367565b60405180910390fd5b81600560008673ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002060003373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002054101561068a576040517f08c379a0000000000000000000000000000000000000000000000000000000008152600401610681906113d3565b60405180910390fd5b81600460008673ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002060008282546106d99190611422565b9250508190555081600460008573ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff168152602001908152602001600020600082825461072f9190611456565b9250508190555081600560008673ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002060003373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002060008282546107c29190611422565b925050819055508273ffffffffffffffffffffffffffffffffffffffff168473ffffffffffffffffffffffffffffffffffffffff167fddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef846040516108269190611038565b60405180910390a3600190509392505050565b600260009054906101000a900460ff1681565b60008073ffffffffffffffffffffffffffffffffffffffff168373ffffffffffffffffffffffffffffffffffffffff16036108bc576040517f08c379a00000000000000000000000000000000000000000000000000000000081526004016108b3906114d6565b60405180910390fd5b81600360008282546108ce9190611456565b9250508190555081600460008573ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002060008282546109249190611456565b925050819055508273ffffffffffffffffffffffffffffffffffffffff16600073ffffffffffffffffffffffffffffffffffffffff167fddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef846040516109899190611038565b60405180910390a36001905092915050565b600081600460003373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff168152602001908152602001600020541015610a1f576040517f08c379a0000000000000000000000000000000000000000000000000000000008152600401610a1690611542565b60405180910390fd5b8160036000828254610a319190611422565b9250508190555081600460003373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020016000206000828254610a879190611422565b92505081905550600073ffffffffffffffffffffffffffffffffffffffff163373ffffffffffffffffffffffffffffffffffffffff167fddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef84604051610aec9190611038565b60405180910390a360019050919050565b6000600460008373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff168152602001908152602001600020549050919050565b60018054610b53906111a6565b80601f0160208091040260200160405190810160405280929190818152602001828054610b7f906111a6565b8015610bcc5780601f10610ba157610100808354040283529160200191610bcc565b820191906000526020600020905b815481529060010190602001808311610baf57829003601f168201915b505050505081565b60008073ffffffffffffffffffffffffffffffffffffffff168373ffffffffffffffffffffffffffffffffffffffff1603610c44576040517f08c379a0000000000000000000000000000000000000000000000000000000008152600401610c3b906112fb565b60405180910390fd5b81600460003373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff168152602001908152602001600020541015610cc6576040517f08c379a0000000000000000000000000000000000000000000000000000000008152600401610cbd90611367565b60405180910390fd5b81600460003373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020016000206000828254610d159190611422565b9250508190555081600460008573ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020016000206000828254610d6b9190611456565b925050819055508273ffffffffffffffffffffffffffffffffffffffff163373ffffffffffffffffffffffffffffffffffffffff167fddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef84604051610dcf9190611038565b60405180910390a36001905092915050565b6000600560008473ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002060008373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002054905092915050565b600081519050919050565b600082825260208201905092915050565b60005b83811015610ea2578082015181840152602081019050610e87565b60008484015250505050565b6000601f19601f8301169050919050565b6000610eca82610e68565b610ed48185610e73565b9350610ee4818560208601610e84565b610eed81610eae565b840191505092915050565b60006020820190508181036000830152610f128184610ebf565b905092915050565b600080fd5b600073ffffffffffffffffffffffffffffffffffffffff82169050919050565b6000610f4a82610f1f565b9050919050565b610f5a81610f3f565b8114610f6557600080fd5b50565b600081359050610f7781610f51565b92915050565b6000819050919050565b610f9081610f7d565b8114610f9b57600080fd5b50565b600081359050610fad81610f87565b92915050565b60008060408385031215610fca57610fc9610f1a565b5b6000610fd885828601610f68565b9250506020610fe985828601610f9e565b9150509250929050565b60008115159050919050565b61100881610ff3565b82525050565b60006020820190506110236000830184610fff565b92915050565b61103281610f7d565b82525050565b600060208201905061104d6000830184611029565b92915050565b60008060006060848603121561106c5761106b610f1a565b5b600061107a86828701610f68565b935050602061108b86828701610f68565b925050604061109c86828701610f9e565b9150509250925092565b600060ff82169050919050565b6110bc816110a6565b82525050565b60006020820190506110d760008301846110b3565b92915050565b6000602082840312156110f3576110f2610f1a565b5b600061110184828501610f9e565b91505092915050565b6000602082840312156111205761111f610f1a565b5b600061112e84828501610f68565b91505092915050565b6000806040838503121561114e5761114d610f1a565b5b600061115c85828601610f68565b925050602061116d85828601610f68565b9150509250929050565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052602260045260246000fd5b600060028204905060018216806111be57607f821691505b6020821081036111d1576111d0611177565b5b50919050565b7f417070726f766520746f207a65726f2061646472657373000000000000000000600082015250565b600061120d601783610e73565b9150611218826111d7565b602082019050919050565b6000602082019050818103600083015261123c81611200565b9050919050565b7f5472616e736665722066726f6d207a65726f2061646472657373000000000000600082015250565b6000611279601a83610e73565b915061128482611243565b602082019050919050565b600060208201905081810360008301526112a88161126c565b9050919050565b7f5472616e7366657220746f207a65726f20616464726573730000000000000000600082015250565b60006112e5601883610e73565b91506112f0826112af565b602082019050919050565b60006020820190508181036000830152611314816112d8565b9050919050565b7f496e73756666696369656e742062616c616e6365000000000000000000000000600082015250565b6000611351601483610e73565b915061135c8261131b565b602082019050919050565b6000602082019050818103600083015261138081611344565b9050919050565b7f416c6c6f77616e63652065786365656465640000000000000000000000000000600082015250565b60006113bd601283610e73565b91506113c882611387565b602082019050919050565b600060208201905081810360008301526113ec816113b0565b9050919050565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601160045260246000fd5b600061142d82610f7d565b915061143883610f7d565b92508282039050818111156114505761144f6113f3565b5b92915050565b600061146182610f7d565b915061146c83610f7d565b9250828201905080821115611484576114836113f3565b5b92915050565b7f4d696e7420746f207a65726f2061646472657373000000000000000000000000600082015250565b60006114c0601483610e73565b91506114cb8261148a565b602082019050919050565b600060208201905081810360008301526114ef816114b3565b9050919050565b7f496e73756666696369656e742062616c616e636520746f206275726e00000000600082015250565b600061152c601c83610e73565b9150611537826114f6565b602082019050919050565b6000602082019050818103600083015261155b8161151f565b905091905056fea264697066735822122054a8f8277b80f6abf9833f89259a466f9e5e61ffdecfd8b0ea630286c749e3d564736f6c63430008120033"

        # Instantiate and deploy contract
        erc = self._web3.eth.contract(abi=abi, bytecode=bytecode)

        # Submit the transaction that deploys the contract
        tx_hash = erc.constructor(name, symbol, 18, int(supply)).transact({'from': account.address})

        # Wait for the transaction to be mined, and get the transaction receipt
        tx_receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash)

        # Get contract address
        contract_address = tx_receipt['contractAddress']
        print(f'Contract deployed at: {contract_address}')
        return contract_address

    def get_address(self) -> str:
        try:
            private_key = os.getenv(
                'EVM_PRIVATE_KEY') or os.getenv('ETH_PRIVATE_KEY')
            account = self._web3.eth.account.from_key(private_key)
            return f"Your Ethereum address: {account.address}"
        except Exception as e:
            return f"Failed to get address: {str(e)}"

    def _get_token_address(self, ticker: str) -> Optional[str]:
        """Helper function to get token address from DEXScreener"""
        try:
            response = requests.get(
                f"https://api.dexscreener.com/latest/dex/search?q={ticker}")
            response.raise_for_status()
            data = response.json()
            if not data.get('pairs'):
                return None

            # Filter pairs for the current network (using lowercase for comparison)
            network_pairs = [
                pair for pair in data["pairs"]
                if pair.get("chainId", "").lower() == self.network.lower()
            ]

            # Sort by liquidity/volume
            network_pairs.sort(
                key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0) *
                float(x.get('volume', {}).get('h24', 0) or 0),
                reverse=True
            )

            # Find exact ticker match
            for pair in network_pairs:
                base_token = pair.get("baseToken", {})
                if base_token.get("symbol", "").lower() == ticker.lower():
                    return base_token.get("address")

            return None

        except Exception as error:
            logger.error(f"Error fetching token address: {str(error)}")
            return None

    def get_token_by_ticker(self, ticker: str) -> str:
        try:
            if ticker.lower() in ["eth", "ethereum", "matic"]:
                return f"{self.NATIVE_TOKEN}"
            address = self._get_token_address(ticker)
            if address:
                return address
        except Exception as error:
            return False

    def _get_raw_balance(self, address: str, token_address: Optional[str] = None) -> float:
        """Helper function to get raw balance value"""
        if token_address and token_address.lower() != self.NATIVE_TOKEN.lower():
            contract = self._web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )
            balance = contract.functions.balanceOf(
                Web3.to_checksum_address(address)).call()
            decimals = contract.functions.decimals().call()
            return balance / (10 ** decimals)
        else:
            balance = self._web3.eth.get_balance(
                Web3.to_checksum_address(address))
            return self._web3.from_wei(balance, 'ether')

    def get_balance(self, token_address: Optional[str] = None) -> float:
        """
        Get balance for the configured wallet.
        If token_address is None, the native token balance is returned.
        """
        try:
            private_key = os.getenv(
                'EVM_PRIVATE_KEY') or os.getenv('ETH_PRIVATE_KEY')
            if not private_key:
                return "No wallet private key configured in .env"

            account = self._web3.eth.account.from_key(private_key)

            if token_address is None:
                raw_balance = self._web3.eth.get_balance(account.address)
                return self._web3.from_wei(raw_balance, 'ether')

            token_contract = self._web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )
            decimals = token_contract.functions.decimals().call()
            raw_balance = token_contract.functions.balanceOf(
                account.address).call()
            token_balance = raw_balance / (10 ** decimals)
            return token_balance

        except Exception as e:
            return False

    def _prepare_transfer_tx(self, to_address: str, amount: float, token_address: Optional[str] = None) -> Dict[str, Any]:
        """Prepare transfer transaction with proper gas estimation"""
        try:
            private_key = os.getenv(
                'EVM_PRIVATE_KEY') or os.getenv('ETH_PRIVATE_KEY')
            account = self._web3.eth.account.from_key(private_key)
            nonce = self._web3.eth.get_transaction_count(account.address)
            gas_price = self._web3.eth.gas_price

            if token_address and token_address.lower() != self.NATIVE_TOKEN.lower():
                contract = self._web3.eth.contract(
                    address=Web3.to_checksum_address(token_address),
                    abi=ERC20_ABI
                )
                decimals = contract.functions.decimals().call()
                amount_raw = int(amount * (10 ** decimals))
                tx = contract.functions.transfer(
                    Web3.to_checksum_address(to_address),
                    amount_raw
                ).build_transaction({
                    'from': account.address,
                    'nonce': nonce,
                    'gasPrice': gas_price,
                    'chainId': self.chain_id
                })
            else:
                tx = {
                    'nonce': nonce,
                    'to': Web3.to_checksum_address(to_address),
                    'value': self._web3.to_wei(amount, 'ether'),
                    'gas': 21000,
                    'gasPrice': gas_price,
                    'chainId': self.chain_id
                }
            return tx

        except Exception as e:
            logger.error(f"Failed to prepare transaction: {str(e)}")
            raise

    def transfer(self, to_address: str, amount: float, token_address: Optional[str] = None) -> str:
        """Transfer ETH or tokens with balance validation"""
        try:
            current_balance = self.get_balance(token_address=token_address)
            if current_balance < amount:
                raise ValueError(
                    f"Insufficient balance. Required: {amount}, Available: {current_balance}")
            tx = self._prepare_transfer_tx(to_address, amount, token_address)
            private_key = os.getenv(
                'EVM_PRIVATE_KEY') or os.getenv('ETH_PRIVATE_KEY')
            account = self._web3.eth.account.from_key(private_key)
            signed = account.sign_transaction(tx)
            tx_hash = self._web3.eth.send_raw_transaction(
                signed.rawTransaction)
            tx_url = self._get_explorer_link(tx_hash.hex())
            return tx_url

        except Exception as e:
            logger.error(f"Transfer failed: {str(e)}")
            raise

    def _get_swap_route(self, token_in: str, token_out: str, amount: float, sender: str) -> Dict:
        """Get optimal swap route from Kyberswap API"""
        try:
            url = f"{self.aggregator_api}/routes"
            if token_in.lower() == self.NATIVE_TOKEN.lower():
                amount_raw = self._web3.to_wei(amount, 'ether')
            else:
                token_contract = self._web3.eth.contract(
                    address=Web3.to_checksum_address(token_in),
                    abi=ERC20_ABI
                )
                decimals = token_contract.functions.decimals().call()
                amount_raw = int(amount * (10 ** decimals))

            headers = {"x-client-id": "zerepy"}
            params = {
                "tokenIn": token_in,
                "tokenOut": token_out,
                "amountIn": str(amount_raw),
                "to": sender,
                "gasInclude": "true"
            }
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0:
                raise ValueError(f"API error: {data.get('message')}")
            return data["data"]

        except Exception as e:
            logger.error(f"Failed to get swap route: {str(e)}")
            raise

    def _build_swap_tx(self, token_in: str, token_out: str, amount: float, slippage: float, route_data: Dict) -> Dict[str, Any]:
        """Build swap transaction using route data"""
        try:
            private_key = os.getenv(
                'EVM_PRIVATE_KEY') or os.getenv('ETH_PRIVATE_KEY')
            account = self._web3.eth.account.from_key(private_key)
            url = f"{self.aggregator_api}/route/build"
            headers = {"x-client-id": "zerepy"}
            payload = {
                "routeSummary": route_data["routeSummary"],
                "sender": account.address,
                "recipient": account.address,
                "slippageTolerance": int(slippage * 100),
                "deadline": int(time.time() + 1200),
                "source": "zerepy"
            }
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0:
                raise ValueError(f"API error: {data.get('message')}")
            tx = {
                'from': account.address,
                'to': Web3.to_checksum_address(route_data["routerAddress"]),
                'data': data["data"]["data"],
                'value': self._web3.to_wei(amount, 'ether') if token_in.lower() == self.NATIVE_TOKEN.lower() else 0,
                'nonce': self._web3.eth.get_transaction_count(account.address),
                'gasPrice': self._web3.eth.gas_price,
                'chainId': self.chain_id
            }
            try:
                gas_estimate = self._web3.eth.estimate_gas(tx)
                tx['gas'] = int(gas_estimate * 1.2)
            except Exception as e:
                logger.warning(
                    f"Gas estimation failed: {e}, using default gas limit")
                tx['gas'] = 500000
            return tx

        except Exception as e:
            logger.error(f"Failed to build swap transaction: {str(e)}")
            raise

    def _handle_token_approval(self, token_address: str, spender_address: str, amount: int) -> Optional[str]:
        """Handle token approval for spender"""
        try:
            private_key = os.getenv(
                'EVM_PRIVATE_KEY') or os.getenv('ETH_PRIVATE_KEY')
            account = self._web3.eth.account.from_key(private_key)
            token_contract = self._web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )
            current_allowance = token_contract.functions.allowance(
                account.address, spender_address).call()
            if current_allowance < amount:
                approve_tx = token_contract.functions.approve(
                    spender_address,
                    amount
                ).build_transaction({
                    'from': account.address,
                    'nonce': self._web3.eth.get_transaction_count(account.address),
                    'gasPrice': self._web3.eth.gas_price,
                    'chainId': self.chain_id
                })
                try:
                    gas_estimate = self._web3.eth.estimate_gas(approve_tx)
                    approve_tx['gas'] = int(gas_estimate * 1.1)
                except Exception as e:
                    logger.warning(
                        f"Approval gas estimation failed: {e}, using default")
                    approve_tx['gas'] = 100000
                signed_approve = account.sign_transaction(approve_tx)
                tx_hash = self._web3.eth.send_raw_transaction(
                    signed_approve.rawTransaction)
                receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash)
                if receipt['status'] != 1:
                    raise ValueError("Token approval failed")
                return tx_hash.hex()
            return None

        except Exception as e:
            logger.error(f"Token approval failed: {str(e)}")
            raise

    def swap(self, token_in: str, token_out: str, amount: float, slippage: float = 0.5) -> str:
        """Execute token swap using Kyberswap aggregator"""
        try:
            private_key = os.getenv(
                "EVM_PRIVATE_KEY") or os.getenv("ETH_PRIVATE_KEY")
            account = self._web3.eth.account.from_key(private_key)
            current_balance = self.get_balance(
                token_address=None if token_in.lower() == self.NATIVE_TOKEN.lower() else token_in
            )
            if current_balance < amount:
                raise ValueError(
                    f"Insufficient balance. Required: {amount}, Available: {current_balance}")
            route_data = self._get_swap_route(
                token_in, token_out, amount, account.address)
            if token_in.lower() != self.NATIVE_TOKEN.lower():
                router_address = route_data["routerAddress"]
                if token_in.lower() == "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2".lower():
                    amount_raw = self._web3.to_wei(amount, 'ether')
                else:
                    token_contract = self._web3.eth.contract(
                        address=Web3.to_checksum_address(token_in),
                        abi=ERC20_ABI
                    )
                    decimals = token_contract.functions.decimals().call()
                    amount_raw = int(amount * (10 ** decimals))
                approval_hash = self._handle_token_approval(
                    token_in, router_address, amount_raw)
                if approval_hash:
                    logger.info(
                        f"Token approval transaction: {self._get_explorer_link(approval_hash)}")
            swap_tx = self._build_swap_tx(
                token_in, token_out, amount, slippage, route_data)
            signed_tx = account.sign_transaction(swap_tx)
            tx_hash = self._web3.eth.send_raw_transaction(
                signed_tx.rawTransaction)
            tx_url = self._get_explorer_link(tx_hash.hex())
            return (f"Swap transaction sent! (allow time for scanner to populate it):\nTransaction: {tx_url}")

        except Exception as e:
            return f"Swap failed: {str(e)}"

    def perform_action(self, action_name: str, kwargs: Dict[str, Any]) -> Any:
        """Execute an Ethereum action with validation"""
        if action_name not in self.actions:
            raise KeyError(f"Unknown action: {action_name}")
        load_dotenv()
        if not self.is_configured(verbose=True):
            raise EthereumConnectionError(
                "Ethereum connection is not properly configured")
        action = self.actions[action_name]
        errors = action.validate_params(kwargs)
        if errors:
            raise ValueError(f"Invalid parameters: {', '.join(errors)}")
        method_name = action_name.replace('-', '_')
        method = getattr(self, method_name)
        return method(**kwargs)
