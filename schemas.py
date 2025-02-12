bank_statement_schema = {
    "name": "bank-statement-analyzer",
    "description": "Analyzes bank statements (Bankauszug) for key information",
    "scenario": "document",
    "fields": [
        {
            "name": "summary",
            "type": "string",
            "description": "Name of the account holder",
        },
        {
            "name": "account_number",
            "type": "string",
            "description": "Bank account number",
        },
        {
            "name": "transactions",
            "type": "string",
            "description": "comma separeted of transactions (date, description, amount)",
        },
        {
            "name": "balance",
            "type": "string",
            "description": "Current balance on the statement",
        },
    ],
}

pay_slip_schema = {
    "name": "paySlipAnalyzer",
    "description": "Analyzer for pay slips (Lohnausweis)",
    "scenario": "document",
    "fields": [
        {
            "name": "employee_name",
            "type": "string",
            "description": "Name of the employee",
        },
        {
            "name": "employer_name",
            "type": "string",
            "description": "Name of the employer",
        },
        {
            "name": "gross_salary",
            "type": "string",
            "description": "Gross salary amount",
        },
        {
            "name": "net_salary",
            "type": "string",
            "description": "Net salary amount",
        },
        {
            "name": "deductions",
            "type": "string",
            "description": "Comma seperated list of deductions and amounts",
        },
    ],
}


def get_analyzer_schema(doc_type: str):
    """
    Return the appropriate schema based on doc_type. 
    doc_type is expected to be 'Bankauszug' or 'Lohnausweis'.
    """
    if doc_type.lower() == "bankauszug":
        return bank_statement_schema
    elif doc_type.lower() == "lohnausweis":
        return pay_slip_schema
    else:
        raise ValueError(f"No schema found for doc_type: {doc_type}")
