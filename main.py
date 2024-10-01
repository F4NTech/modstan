import sys
import configparser
from pyModbusTCP.client import ModbusClient
import logging
import datetime
import time
import struct
import os

# Function to load configuration from a file
def load_config(file_path):
    config = configparser.ConfigParser()
    config.read(file_path)
    return config

# Function to swap bytes based on format
def swap_bytes(registers, format):
    if format == 'ABCD':
        return registers
    elif format == 'CDAB':
        return registers[::-1]
    elif format == 'AB':  # No swap, just return the registers as they are
        return registers
    elif format == 'BA':  # Swap bytes within each 16-bit register
        swapped = []
        for reg in registers:
            swapped.append(((reg & 0xFF) << 8) | ((reg >> 8) & 0xFF))
        return swapped
    elif format == 'BADC':
        swapped = []
        for reg in registers:
            swapped.append(((reg & 0xFF) << 8) | ((reg >> 8) & 0xFF))
        return swapped
    elif format == 'DCBA':
        return swap_bytes(registers[::-1], 'BADC')
    else:
        raise ValueError(f"Unsupported byte format: {format}")

# Function to convert register data based on type and byte format
def convert_registers(registers, data_type, byte_format):
    registers = swap_bytes(registers, byte_format)
    
    if data_type == 'uint16':
        return registers[0]
    elif data_type == 'int16':
        return struct.unpack('>h', struct.pack('>H', registers[0]))[0]
    elif data_type == 'uint32':
        return struct.unpack('>I', struct.pack('>HH', registers[0], registers[1]))[0]
    elif data_type == 'int32':
        return struct.unpack('>i', struct.pack('>HH', registers[0], registers[1]))[0]
    elif data_type == 'uint64':
        return struct.unpack('>Q', struct.pack('>HHHH', registers[0], registers[1], registers[2], registers[3]))[0]
    elif data_type == 'int64':
        return struct.unpack('>q', struct.pack('>HHHH', registers[0], registers[1], registers[2], registers[3]))[0]
    elif data_type == 'float32':
        return struct.unpack('>f', struct.pack('>HH', registers[0], registers[1]))[0]
    elif data_type == 'float64':
        return struct.unpack('>d', struct.pack('>HHHH', registers[0], registers[1], registers[2], registers[3]))[0]
    else:
        raise ValueError(f"Unsupported data type: {data_type}")

# Read registers based on configuration for each slave
def read_configured_registers(config, client):
    all_registers = {}
    for register_name, register_info in config['REGISTERS'].items():
        try:
            function_code, address, quantity, data_type, scale, *optional_byte_format = [x.strip() for x in register_info.split(',')]
            address = int(address)
            quantity = int(quantity)
            scale = float(scale)
            data_type = data_type.strip()
            
            byte_format = optional_byte_format[0].strip() if optional_byte_format else 'ABCD'
            function_code = int(function_code)

            start_time = time.time()
            if function_code == 3:
                registers = client.read_holding_registers(address, quantity)
            elif function_code == 4:
                registers = client.read_input_registers(address, quantity)
            else:
                logging.error(f"Unsupported function code: {function_code}")
                continue

            elapsed_time = (time.time() - start_time) * 1000  # Convert to milliseconds

            if registers is None:
                logging.error(f"Error reading register {register_name} at address {address} using function code {function_code}")
                continue

            all_registers[register_name] = {
                'raw': registers,
                'scale': scale,
                'data_type': data_type,
                'address': address,
                'quantity': quantity,
                'function_code': function_code,
                'byte_format': byte_format,
                'ping': elapsed_time
            }

        except ValueError as e:
            logging.error(f"Error parsing register {register_name}: {e}")
            continue
    
    return all_registers

# Process registers after reading them for each slave
def process_registers(all_registers, device_name, config):
    owner_data = config['OWNER']
    customer_id = owner_data.get('customer_id', 'Unknown')
    tag_host = owner_data.get('tag_host', 'Unknown')
    tag_name = owner_data.get('tag_name', 'Unknown')

    # Dictionary to store scaled values for database saving
    scaled_values = {}

    for register_name, register_data in all_registers.items():
        raw_registers = register_data['raw']
        scale = register_data['scale']
        data_type = register_data['data_type']
        address = register_data['address']
        quantity = register_data['quantity']
        function_code = register_data['function_code']
        byte_format = register_data['byte_format']
        ping = register_data['ping']

        try:
            raw_value = convert_registers(raw_registers, data_type, byte_format)
            scaled_value = raw_value * scale
            
            hex_value = " ".join(f"0x{reg:04X}" for reg in raw_registers)

            logging.info(f"Customer: {customer_id:<3} || Host: {tag_host:<15} || Tag: {tag_name:<15} || "
                         f"Device: {device_name:<8} || Register: {register_name:<10}|| Address: {address:<5} || "
                         f"Quantity: {quantity:<2} || Function Code: {function_code:<2} || Hex Value: {hex_value:<35}|| "
                         f"Raw Value: {raw_value:<30} || Scaled Value: {scaled_value:<35} || Data Type: {data_type:<8} || Byte Format: {byte_format:<7} || Ping Time: {ping:8.2f} ms")
            
            # Save scaled value for this register
            scaled_values[register_name] = scaled_value
            print(f"Success reading register {register_name}.")
        
        except KeyboardInterrupt:
        # Allow script to be stopped with Ctrl+C
            logging.info("Script interrupted by user.")
        
        except Exception as e:
            logging.error(f"Error processing register {register_name} for device {device_name}: {e}")

# Function to clean up old logs (older than 7 days)
def cleanup_old_logs(log_file_path):
    if not os.path.exists(log_file_path):
        logging.error(f"Log file {log_file_path} not found.")
        return

    # Get the current time
    now = datetime.datetime.now()
    # Define the time limit (7 days ago)
    time_limit = now - datetime.timedelta(days=7)

    # Create a temporary file to write cleaned data
    temp_file_path = log_file_path + ".tmp"

    try:
        with open(log_file_path, 'r') as log_file, open(temp_file_path, 'w') as temp_file:
            for line in log_file:
                try:
                    # Parse the timestamp from each log entry (assuming it's the first field in the log format)
                    log_time_str = line.split(' - ')[0]
                    log_time = datetime.datetime.strptime(log_time_str, '%Y-%m-%d %H:%M:%S')

                    # Write the line to the temp file if it's newer than the time limit
                    if log_time > time_limit:
                        temp_file.write(line)

                except Exception as e:
                    # In case of format error or any exception, skip the line
                    logging.error(f"Error processing log line: {line}. Error: {e}")

        # Replace the original log file with the cleaned temp file
        os.replace(temp_file_path, log_file_path)
        logging.info(f"Old log entries cleaned from {log_file_path}.")

    except Exception as e:
        logging.error(f"Error during log cleanup for file {log_file_path}: {e}")

# Main function to process a specific configuration
def main(config_file):
    file_name = os.path.basename(config_file)
    config = load_config(config_file)
    device_name = config['DEVICE'].get('name', 'Unknown')

    # log_file_path = f'/etc/modstar{file_name.replace("modstar-", "").replace(".conf", "")}.log'       #linux
    log_file_path = f'{file_name.replace("modstar-", "").replace(".conf", "")}.log'                     #windows
    
    # Set up logging
    logging.basicConfig(filename=log_file_path, level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # Clean up old logs before reading registers
    cleanup_old_logs(log_file_path)

    # Modbus client setup
    modbus_client = ModbusClient(host=config['MODBUS'].get('host'), port=int(config['MODBUS'].get('port')))
    modbus_client.open()

    # Define a running flag
    running = True
    try:
        while running:
            # Reading registers and processing them
            all_registers = read_configured_registers(config, modbus_client)
            process_registers(all_registers, device_name, config)
            
            # Sleep for the defined interval in the config file (e.g., 5 seconds)
            interval = int(config['DEVICE'].get('interval', 5))  # default to 5 seconds if not set
            time.sleep(interval)

    except KeyboardInterrupt:
        # Allow script to be stopped with Ctrl+C
        logging.info("Script interrupted by user.")

    finally:
        # Close the Modbus client after use
        modbus_client.close()
        logging.info("Modbus client closed.")

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <config_file>")
        sys.exit(1)

    config_file = sys.argv[1]
    main(config_file)
