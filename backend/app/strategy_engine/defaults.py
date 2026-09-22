"""Small illustrative study chart, deliberately not sold as GTO or calibrated advice."""
from .models import PreflopRule


def default_rules():
    tight = "AA,KK,QQ,JJ,TT,99,AK,AQs,AJs,KQs"
    middle = tight + ",88,77,ATs,AQo,KJs,QJs,JTs"
    late = middle + ",66,55,44,33,22,A9s,A8s,A7s,A6s,A5s,A4s,A3s,A2s,ATo,KQo,KTs,QTs,T9s,98s"
    rules = [PreflopRule(id="open-early", scenario="unopened", positions=("UTG", "HJ"), raise_range=tight),
             PreflopRule(id="open-cutoff", scenario="unopened", positions=("CO",), raise_range=middle),
             PreflopRule(id="open-late", scenario="unopened", positions=("BTN", "SB", "BTN/SB"), raise_range=late),
             PreflopRule(id="isolate-limpers", scenario="limped", positions=("UTG", "HJ", "CO", "BTN", "SB", "BB", "BTN/SB"), raise_range=tight, open_to_bb=3),
             PreflopRule(id="face-one-raise", scenario="single_raise", positions=("UTG", "HJ", "CO", "BTN", "SB", "BB", "BTN/SB"),
                         raise_range="AA,KK,QQ,AK", call_range="JJ,TT,99,AQs,AJs,KQs")]
    return tuple(rules)
