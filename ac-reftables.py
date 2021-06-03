# recursively unroll RLTs and level compare vs creatures

from mysql.connector import connect, Error
import time

def open_sql_db(db_user, db_pass):
    try:
        db = connect(host = 'localhost',
                     database = 'acore_world',
                     user = db_user,
                     password = db_pass)
        if db.is_connected():
            print('Connected to AzCore database.')
    except Error as e:
        print(e)

    return db, db.cursor()

def process_data(found, gen_sql):
    oli = {}
    output, sqlout = [], []
    for item in found:
        npc_id, reftable = item[0], item[3]
        if npc_id not in oli or reftable not in oli[npc_id]:
            oli[npc_id] = {reftable: 1}
        else:
            oli[npc_id][reftable] += 1

    for item in found:
        npc_id, reftable = item[0], item[3]
        if npc_id in oli and reftable in oli[npc_id]:
            output.append(f'ID: {npc_id}, {item[1]}, lvl {item[2]} -> '\
                          f'CLT {item[8]} -> '\
                          f'RLT {reftable} -> Item ID: {item[4]}, '\
                          f'lvl {item[6]} {item[5]} and {oli[npc_id][reftable]} others\n')
            if gen_sql: #QQQQ check SQL quotes vs confirmed source
                sqlout.append(f'-- Deletes RFT {reftable} from lvl {item[2]} NPC '\
                              f'{item[1]}, ID: {npc_id} due to {item[7]} level gap.\n')
                sqlout.append(f'DELETE FROM `creature_loot_template` WHERE '\
                              f'`Entry` = {item[8]} AND `Reference` = {reftable};\n\n')

            del oli[npc_id][reftable]

    return ''.join(output), ''.join(sqlout)

def export_data(found, levelstr, gen_sql=False):
    outstr, sqlout = process_data(found, gen_sql)
    outfilename = f'ac-rlt-overlevel-{levelstr}.txt'
    with open(outfilename, 'w') as outfile:
        outfile.write(outstr)
    print(f'Data written to file {outfilename}.')

    if sqlout != []:
        sqloutfilename = outfilename[:-4] + '-sql.txt'
        with open(sqloutfilename, 'w') as sqloutfile:
            sqloutfile.write(sqlout)
        print(f'SQL commands written to {sqloutfilename}.')

def build_rlt_table(db, cursor):
    rlts = {}
    unrolled = {}
    print('Building RLT table...', end='')
    #db, cursor = open_sql_db(db_user, db_pass)
    query = ('SELECT rlt.entry, rlt.reference '
             'FROM `reference_loot_template` rlt '
             'WHERE rlt.reference != 0')
    cursor.execute(query)
    for rlt in cursor.fetchall():
        k, v = rlt
        rlts[k] = rlts.get(k, []) + [v]

    #rlts = {k:list(set(v)) for k, v in rlts.items()}

    for k, v in rlts.items():
        queue = set(v)
        while queue:
            link = queue.pop()
            if link in rlts:
                for l in rlts[link]:
                    queue.add(l)
                if link not in v:
                    v.append(link)
        unrolled[k] = list(set(v))

    print('done.')
    return unrolled

def get_rlt_table(db, cursor, rlt_id):
    # returns all items in a specificed RLT that meet query criteria
    items = []
    #print(f'Reading RLT {rlt_id}.')

    query = ('SELECT it.entry, it.name, it.ItemLevel '
             'FROM `reference_loot_template` rlt '
             'JOIN `item_template` it ON rlt.item = it.entry '
             'WHERE it.startquest = 0 AND it.class IN (2, 4) '
             'AND rlt.reference = 0 AND it.Quality > 0 '
             'AND it.inventorytype NOT IN (0, 4, 19, 20, 23) '
             f'AND rlt.entry = {rlt_id}')
    cursor.execute(query)
    for item in cursor.fetchall():
        it_entry, it_name, it_itemlevel = item
        items.append(item)

    return {rlt_id: items}

def scan_reftables(db_user, db_pass, min_npc_level=1, max_npc_level=60, leveldiff=4):
    found = []
    npcs, rlt_tables = {}, {}
    db, cursor = open_sql_db(db_user, db_pass)

    rlts = build_rlt_table(db, cursor)

    query = ('SELECT DISTINCT ct.entry, ct.name, ct.maxlevel, clt.entry, rlt.entry '
             'FROM `creature_template` ct '
             'JOIN `creature_loot_template` clt ON ct.lootid = clt.entry '
             'JOIN `reference_loot_template` rlt ON clt.reference = rlt.entry '
             f'WHERE ct.minlevel >= {min_npc_level} '
             f'AND ct.maxlevel <= {max_npc_level} AND ct.rank = 0 '
             'AND clt.reference != 0')

    cursor.execute(query)
    npclist = cursor.fetchall()
    listsize = len(npclist)

    # build NPC -> NPC info + RLT IDs lookup table
    for count, npc in enumerate(npclist):
        #print(f'Scanning {npc[1]}')
        new_id = npc[0]
        if new_id not in npcs:
            npcs[new_id] = [npc[1], npc[2], npc[3], npc[4]]
        else:
            npcs[new_id].append(npc[4])

    for npc_id, npcdata in npcs.items():
        npc_name, npc_maxlvl, npc_lootid = npcdata[0], npcdata[1], npcdata[2]
        curr_rlts = npcdata[3:]

        #add nested RLTs
        addlist = []
        for x in curr_rlts:
            if x in rlts:
                addlist += rlts[x]
        curr_rlts = list(set(curr_rlts + addlist))

        for rlt_id in curr_rlts:
            if rlt_id not in rlt_tables: #cache RLT
                rlt_tables.update(get_rlt_table(db, cursor, rlt_id))

            for item in rlt_tables[rlt_id]:
                if item[2] >= npc_maxlvl + leveldiff:
                    new = [npc_id, npc_name, npc_maxlvl, rlt_id, item[0], item[1],
                           item[2], item[2] - npc_maxlvl, npc_lootid]
                    found.append(new)

    # sort by ID and then level diff
    found.sort(key = lambda x: x[0], reverse=True)
    found.sort(key = lambda x: x[7], reverse=True)
    return found

def main():
    start = time.time()
    db_user = 'acore'
    db_pass = 'acore'
    min_lvl, max_lvl = 1, 58
    found = scan_reftables(db_user, db_pass, min_lvl, max_lvl, 5)
    export_data(found, f'{min_lvl}-{max_lvl}', gen_sql=True)
    print(f'Run complete in {time.time() - start:.2f} secs.')

if __name__ == '__main__':
    main()
