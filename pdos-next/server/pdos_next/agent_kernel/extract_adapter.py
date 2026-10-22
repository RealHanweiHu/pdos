"""Wire evidence.extract into run read tools with replay revalidation."""


class ExtractReadAdapter:
    def __init__(self, service, graph):
        self.service, self.graph = service, graph

    def __call__(self, scope, arguments):
        return self.service.extract(scope, arguments, graph=self.graph)

    def restore(self, scope, arguments, previous):
        return self.service.restore(scope, arguments, previous)

    def handlers(self):
        return {"evidence.extract": self}

    def restores(self):
        return {"evidence.extract": self.restore}
