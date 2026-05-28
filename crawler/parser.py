"""Transform TDX API responses into database-ready structures."""

from datetime import time
from typing import Optional


# TDX StationID → Chinese name (used to match against our stations table)
TDX_STATION_ID_TO_NAME: dict[str, str] = {
    "0990": "南港",
    "1000": "台北",
    "1010": "板橋",
    "1020": "桃園",
    "1030": "新竹",
    "1035": "苗栗",
    "1040": "台中",
    "1043": "彰化",
    "1047": "雲林",
    "1050": "嘉義",
    "1060": "台南",
    "1070": "左營",
}


def parse_time(value: Optional[str]) -> Optional[time]:
    """Parse 'HH:MM' or 'HH:MM:SS' string into time object."""
    if not value:
        return None
    parts = value.strip().split(":")
    try:
        h, m = int(parts[0]), int(parts[1])
        # Handle overnight: TDX may return >24h for trains past midnight
        h = h % 24
        return time(h, m)
    except (ValueError, IndexError):
        return None


def tdx_train_type(service_type: int) -> str:
    """Map TDX ServiceType integer to our train_type string."""
    # TDX: 1=普通車(standard), 2=直達車(express)
    return "express" if service_type == 2 else "standard"


def parse_daily_timetable(tdx_entries: list[dict]) -> list[dict]:
    """
    Convert TDX DailyTimetable response to a list of parsed schedule dicts.

    Each returned dict has:
      train_no, train_type, stops: [{tdx_station_id, arrival, departure}]
    """
    results = []
    for entry in tdx_entries:
        train_no = entry.get("TrainNo", "")
        service_type = entry.get("TrainTypeCode") or entry.get("ServiceType") or 1
        stops_raw = entry.get("StopTimes", [])

        stops = []
        for stop in stops_raw:
            station_id = stop.get("StationID", "")
            arrival = parse_time(stop.get("ArrivalTime"))
            departure = parse_time(stop.get("DepartureTime"))
            stops.append({
                "tdx_station_id": station_id,
                "arrival": arrival,
                "departure": departure,
            })

        if train_no and stops:
            results.append({
                "train_no": train_no,
                "train_type": tdx_train_type(service_type),
                "stops": stops,
            })
    return results


def parse_general_timetable(tdx_entries: list[dict]) -> list[dict]:
    """
    Parse TDX GeneralTimetable response.

    Actual structure per entry:
      {GeneralTimetable: {GeneralTrainInfo: {TrainNo, Direction, ...}, StopTimes: [...]}}
    """
    results = []
    for entry in tdx_entries:
        general = entry.get("GeneralTimetable", entry)
        train_info = general.get("GeneralTrainInfo", {})
        train_no = train_info.get("TrainNo", "")

        # Infer type from train number range (THSR convention)
        try:
            num = int(train_no)
            train_type = "express" if num < 300 else "standard"
        except ValueError:
            train_type = "standard"

        stops_raw = general.get("StopTimes", [])
        stops = []
        for stop in stops_raw:
            station_id = stop.get("StationID", "")
            arrival   = parse_time(stop.get("ArrivalTime"))
            departure = parse_time(stop.get("DepartureTime"))
            stops.append({
                "tdx_station_id": station_id,
                "arrival": arrival,
                "departure": departure,
            })

        if train_no and stops:
            results.append({
                "train_no": train_no,
                "train_type": train_type,
                "stops": stops,
            })
    return results


def parse_od_fares(tdx_fares: list[dict]) -> list[dict]:
    """
    Convert TDX ODFare response to price list.

    TDX fare fields:
      TicketType: 1=全票, 8=孩童
      CabinClass:  1=標準, 2=商務, 3=自由座

    Returns: [{start_tdx_id, end_tdx_id, standard, business}]
    """
    results = []
    for entry in tdx_fares:
        start_id = entry.get("OriginStationID", "")
        end_id   = entry.get("DestinationStationID", "")
        fares    = entry.get("Fares", [])
        std_price = biz_price = None
        for fare in fares:
            if fare.get("TicketType") != 1:
                continue  # only full-price tickets
            cabin = fare.get("CabinClass")
            price = fare.get("Price")
            if cabin == 1:
                std_price = price
            elif cabin == 2:
                biz_price = price
        if start_id and end_id and std_price is not None:
            results.append({
                "start_tdx_id": start_id,
                "end_tdx_id": end_id,
                "standard": std_price,
                "business": biz_price or int(std_price * 1.65),
            })
    return results
