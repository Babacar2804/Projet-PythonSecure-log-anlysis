"""logengine : moteur d'ingestion, de nettoyage et d'analyse de logs.

Organisation des modules :
    generator    -> fabrique le jeu de données (logs volumineux et "sales")
    ingestion    -> Module 1 : lecture paresseuse avec yield / yield from
    parsing      -> Module 1/2 : ligne brute -> dict, routage par match-case
    transform    -> Module 2 : nettoyage et normalisation (map, filter, lambda)
    aggregation  -> Module 3 : statistiques (defaultdict, set, frozenset)
    detection    -> Module 3 : détection de force brute (while/for/else)
    rules        -> Module 4 : moteur de règles (*args, **kwargs)
    audit        -> Module 4 : introspection avec globals() / locals()
    report       -> exports JSON / CSV et graphiques
"""
