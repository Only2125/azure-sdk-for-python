import azure.cosmos.cosmos_client as cosmos_client
import azure.cosmos.errors as errors
from azure.cosmos.partition_key import PartitionKey
import datetime

import samples.Shared.config as cfg

# ----------------------------------------------------------------------------------------------------------
# Prerequistes - 
# 
# 1. An Azure Cosmos account - 
#    https:#azure.microsoft.com/en-us/documentation/articles/documentdb-create-account/
#
# 2. Microsoft Azure Cosmos PyPi package - 
#    https://pypi.python.org/pypi/azure-cosmos/
# ----------------------------------------------------------------------------------------------------------
# Sample - demonstrates the basic CRUD operations on a Item resource for Azure Cosmos
# ----------------------------------------------------------------------------------------------------------

HOST = cfg.settings['host']
MASTER_KEY = cfg.settings['master_key']
DATABASE_ID = cfg.settings['database_id']
CONTAINER_ID = cfg.settings['container_id']

class IDisposable(cosmos_client.CosmosClient):
    """ A context manager to automatically close an object with a close method
    in a with statement. """

    def __init__(self, obj):
        self.obj = obj

    def __enter__(self):
        return self.obj # bound to target

    def __exit__(self, exception_type, exception_val, trace):
        # extra cleanup in here
        self = None

class ItemManagement:
    
    @staticmethod
    def CreateItems(container):
        print('Creating Items')
        print('\n1.1 Create Item\n')

        # Create a SalesOrder object. This object has nested properties and various types including numbers, DateTimes and strings.
        # This can be saved as JSON as is without converting into rows/columns.
        sales_order = ItemManagement.GetSalesOrder("SalesOrder1")
        container.create_item(body=sales_order)

        # As your app evolves, let's say your object has a new schema. You can insert SalesOrderV2 objects without any 
        # changes to the database tier.
        sales_order2 = ItemManagement.GetSalesOrderV2("SalesOrder2")
        container.create_item(body=sales_order2)

    @staticmethod
    def ReadItem(container, doc_id):
        print('\n1.2 Reading Item by Id\n')

        # Note that Reads require a partition key to be spcified.
        response = container.read_item(item=doc_id, partition_key=doc_id)

        print('Item read by Id {0}'.format(doc_id))
        print('Account Number: {0}'.format(response.get('account_number')))
        print('Subtotal: {0}'.format(response.get('subtotal')))

    @staticmethod
    def ReadItems(container):
        print('\n1.3 - Reading all items in a container\n')

        # NOTE: Use MaxItemCount on Options to control how many items come back per trip to the server
        #       Important to handle throttles whenever you are doing operations such as this that might
        #       result in a 429 (throttled request)
        item_list = list(container.read_all_items(max_item_count=10))
        
        print('Found {0} items'.format(item_list.__len__()))
        
        for doc in item_list:
            print('Item Id: {0}'.format(doc.get('id')))

    @staticmethod
    def QueryItems(container, doc_id):
        print('\n1.4 Querying for an  Item by Id\n')

        # enable_cross_partition_query should be set to True as the collection is partitioned
        items = list(container.query_items(
            query="SELECT * FROM r WHERE r.id=@id",
            parameters=[
                { "name":"@id", "value": doc_id }
            ],
            enable_cross_partition_query=True
        ))

        print('Item queried by Id {0}'.format(items[0].get("id")))

    @staticmethod
    def ReplaceItem(container, doc_id):
        print('\n1.5 Replace an Item\n')

        read_item = container.read_item(item=doc_id, partition_key=doc_id)
        read_item['subtotal'] = read_item['subtotal'] + 1
        response = container.replace_item(item=read_item, body=read_item)

        print('Replaced Item\'s Id is {0}, new subtotal={1}'.format(response['id'], response['subtotal']))

    @staticmethod
    def UpsertItem(container, doc_id):
        print('\n1.6 Upserting an item\n')

        read_item = container.read_item(item=doc_id, partition_key=doc_id)
        read_item['subtotal'] = read_item['subtotal'] + 1
        response = container.upsert_item(body=read_item)

        print('Upserted Item\'s Id is {0}, new subtotal={1}'.format(response['id'], response['subtotal']))

    @staticmethod
    def DeleteItem(container, doc_id):
        print('\n1.7 Deleting Item by Id\n')

        response = container.delete_item(item=doc_id, partition_key=doc_id)

        print('Deleted item\'s Id is {0}'.format(doc_id))

    @staticmethod
    def GetSalesOrder(item_id):
        order1 = {'id' : item_id,
                'account_number' : 'Account1',
                'purchase_order_number' : 'PO18009186470',
                'order_date' : datetime.date(2005,1,10).strftime('%c'),
                'subtotal' : 419.4589,
                'tax_amount' : 12.5838,
                'freight' : 472.3108,
                'total_due' : 985.018,
                'items' : [
                    {'order_qty' : 1,
                     'product_id' : 100,
                     'unit_price' : 418.4589,
                     'line_price' : 418.4589
                    }
                    ],
                'ttl' : 60 * 60 * 24 * 30
                }

        return order1

    @staticmethod
    def GetSalesOrderV2(item_id):
        # notice new fields have been added to the sales order
        order2 = {'id' : item_id,
                'account_number' : 'Account2',
                'purchase_order_number' : 'PO15428132599',
                'order_date' : datetime.date(2005,7,11).strftime('%c'),
                'due_date' : datetime.date(2005,7,21).strftime('%c'),
                'shipped_date' : datetime.date(2005,7,15).strftime('%c'),
                'subtotal' : 6107.0820,
                'tax_amount' : 586.1203,
                'freight' : 183.1626,
                'discount_amt' : 1982.872,
                'total_due' : 4893.3929,
                'items' : [
                    {'order_qty' : 3,
                     'product_code' : 'A-123',      # notice how in item details we no longer reference a ProductId
                     'product_name' : 'Product 1',  # instead we have decided to denormalise our schema and include 
                     'currency_symbol' : '$',       # the Product details relevant to the Order on to the Order directly
                     'currecny_code' : 'USD',       # this is a typical refactor that happens in the course of an application
                     'unit_price' : 17.1,           # that would have previously required schema changes and data migrations etc.
                     'line_price' : 5.7
                    }
                    ],
                'ttl' : 60 * 60 * 24 * 30
                }

        return order2

def run_sample():
    with IDisposable(cosmos_client.CosmosClient(HOST, {'masterKey': MASTER_KEY} )) as client:
        try:
            # setup database for this sample
            try:
                db = client.create_database(id=DATABASE_ID)

            except errors.CosmosResourceExistsError:
                pass

            # setup container for this sample
            try:
                container = db.create_container(id=CONTAINER_ID, partition_key=PartitionKey(path='/id', kind='Hash'))
                print('Container with id \'{0}\' created'.format(CONTAINER_ID))

            except errors.CosmosResourceExistsError:
                print('Container with id \'{0}\' was found'.format(CONTAINER_ID))

            ItemManagement.CreateItems(container)
            ItemManagement.ReadItem(container, 'SalesOrder1')
            ItemManagement.ReadItems(container)
            ItemManagement.QueryItems(container, 'SalesOrder1')
            ItemManagement.ReplaceItem(container, 'SalesOrder1')
            ItemManagement.UpsertItem(container, 'SalesOrder1')
            ItemManagement.DeleteItem(container, 'SalesOrder1')

            # cleanup database after sample
            try:
                client.delete_database(db)

            except errors.CosmosResourceNotFoundError:
                pass

        except errors.CosmosHttpResponseError as e:
            print('\nrun_sample has caught an error. {0}'.format(e.message))
        
        finally:
            print("\nrun_sample done")


if __name__ == '__main__':
    try:
        run_sample()

    except Exception as e:
            print("Top level Error: args:{0}, message:N/A".format(e.args))
