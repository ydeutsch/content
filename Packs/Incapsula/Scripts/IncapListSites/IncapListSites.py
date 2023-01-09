from CommonServerPython import *  # noqa: F401

import demistomock as demisto  # noqa: F401

resp = demisto.executeCommand("incap-list-sites", demisto.args())

if isError(resp[0]):
    demisto.results(resp)
else:
    data = demisto.get(resp[0], "Contents.sites")
    if data:
        data = data if isinstance(data, list) else [data]
        data = [{k: formatCell(row[k]) for k in row} for row in data]
        demisto.results({"ContentsFormat": formats["table"], "Type": entryTypes["note"], "Contents": data})
    else:
        demisto.results("No results.")
