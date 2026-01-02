from huawei_solar.registers import REGISTERS

def get_mdb_number(key):
    try:
        number = str(REGISTERS[key].register)
    except:
        number = '-'
    return number
