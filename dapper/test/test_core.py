from .. import _core as C


def test_feed():
    S = C.Struct(
        [("a", C.UBInt24()),
         ("b", C.Struct([("c", C.Sequence([C.UBInt8(), C.UBInt8()])),
                         ("d", C.UBInt16())]))])

    container = C.Container(a=1, b=C.Container(c=[2, 4], d=3))

    total = C.emit(S, container)
    f = C.FeedContext()

    for idx in range(len(total)):
        part = total[idx:idx+1]
        try:
            complete = C.feed(S, part, f)
        except C.Incomplete:
            pass

    assert container == complete
