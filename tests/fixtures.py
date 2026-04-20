"""Fixtures mirroring the user's actual broker CSV exports."""

# Fidelity — includes all the tricky rows: disclaimer preamble, BUY/SELL,
# DIVIDEND, REINVESTMENT, TRANSFER, empty-symbol, disclaimer footer.
FIDELITY_CSV = """\ufeff
\nRun Date,Action,Symbol,Description,Type,Price ($),Quantity,Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date
12/31/2025,"REINVESTMENT FIDELITY GOVERNMENT CASH RESERVES (FDRXX) (Cash)",FDRXX,"FIDELITY GOVERNMENT CASH RESERVES",Cash,1,27.09,,,,-27.09,4096.52,
12/31/2025,"DIVIDEND RECEIVED FIDELITY GOVERNMENT CASH RESERVES (FDRXX) (Cash)",FDRXX,"FIDELITY GOVERNMENT CASH RESERVES",Cash,,0.000,,,,27.09,4096.52,
12/31/2025,"YOU BOUGHT UIPATH INC CL A (PATH) (Cash)",PATH,"UIPATH INC CL A",Cash,16.54,50,,,,-826.75,4069.43,01/02/2026
12/23/2025,"REINVESTMENT META PLATFORMS INC CLASS A COMMON STOCK (META) (Cash)",META,"META PLATFORMS INC CLASS A COMMON STOCK",Cash,662.11,0.027,,,,-17.87,5697.61,
12/23/2025,"DIVIDEND RECEIVED META PLATFORMS INC CLASS A COMMON STOCK (META) (Cash)",META,"META PLATFORMS INC CLASS A COMMON STOCK",Cash,,0.000,,,,17.87,5715.48,
04/15/2026,"YOU SOLD TESLA MOTORS INC (TSLA) (Cash)",TSLA,"TESLA MOTORS INC",Cash,245.10,-2,,,,490.18,3288.32,04/16/2026
11/06/2025,"TRANSFERRED FROM TO BROKERAGE OPTION (Cash)", ,"No Description",Cash,,0.000,,,,32840.15,32854.00,
"The data and information provided herein are for informational purposes only"
"""

# Robinhood — covers all your trans codes, multi-line Description,
# parenthesized negatives, trailing disclaimer.
ROBINHOOD_CSV = '''"Activity Date","Process Date","Settle Date","Instrument","Description","Trans Code","Quantity","Price","Amount"
"11/7/2025","11/7/2025","11/7/2025","ZETA","Stock Lending","SLIP","","","$0.01"
"10/10/2025","10/10/2025","10/14/2025","ZETA","Zeta Global
CUSIP: 98956A105","Buy","116","$19.26","($2,233.58)"
"9/30/2025","9/30/2025","10/1/2025","HNST","The Honest Company
CUSIP: 438333106","Sell","1","$3.66","$3.66"
"7/3/2025","7/3/2025","7/3/2025","NVDA","Cash Div: R/D 2025-06-11 P/D 2025-07-03 - 10 shares at 0.01","CDIV","","","$0.10"
"2/18/2025","2/18/2025","2/18/2025","SOFI","SoFi Technologies
CUSIP: 83406F102","ACATI","302","",""
"2/18/2025","2/18/2025","2/18/2025","","Interest on Contribution (IRA Match)","MTCH","","","$288.16"
"2/18/2025","2/18/2025","2/18/2025","","ACAT IN control_num = 20250420056711","ACATI","","","$4.43"
""
"","","","","","","","","","Disclaimer"
'''
