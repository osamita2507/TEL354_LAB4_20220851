import yaml
import uuid
import requests

CONTROLLER_IP = '10.100.18.253'


def _get(d, *keys, default=None):
    """Devuelve el primer campo que exista (acepta claves en inglés o español)."""
    for k in keys:
        if k in d:
            return d[k]
    return default


# =====================================================================
#                               CLASES
# =====================================================================
class Student:
    def __init__(self, name, mac, code=None):
        self.name = name
        self.mac = mac
        self.code = code


class Service:
    def __init__(self, name, protocol, port):
        self.name = name
        self.protocol = protocol
        self.port = port


class Server:
    def __init__(self, name, ip, services):
        self.name = name
        self.ip = ip
        self.services = services  # lista de Service

    def get_service(self, name):
        for sv in self.services:
            if str(sv.name).lower() == str(name).lower():
                return sv
        return None


class Course:
    def __init__(self, name, code, state, students=None, servers=None):
        self.name = name
        self.code = code
        self.state = state
        # Identificadores de alumnos (nombre o código, según venga en el YAML)
        self.students = students if students is not None else []
        # Lista de dicts: {"name": "Server 1", "allowed_services": ["ssh", ...]}
        self.servers = servers if servers is not None else []

    def tiene_alumno(self, student):
        return student.name in self.students or (student.code is not None and student.code in self.students)

    def agregar_alumno(self, student):
        if self.tiene_alumno(student):
            return False
        self.students.append(student.code if student.code is not None else student.name)
        return True

    def remover_alumno(self, student):
        for ident in (student.name, student.code):
            if ident is not None and ident in self.students:
                self.students.remove(ident)
                return True
        return False

    def servicios_permitidos(self, server_name):
        for s in self.servers:
            if s["name"] == server_name:
                return s["allowed_services"]
        return None

    def esta_activo(self):
        return str(self.state).upper() in ("DICTANDO", "ACTIVO", "ACTIVE")


# =====================================================================
#                        NETWORK POLICY MANAGER
# =====================================================================
class NetworkPolicyManager:
    def __init__(self):
        self.students = []
        self.servers = []
        self.courses = []
        self.connections = {}  # { handler: {detalles_conexion} }
        self.controller_ip = CONTROLLER_IP

    # ---------------- Búsquedas ----------------
    def buscar_alumno(self, ident):
        for s in self.students:
            if s.name == ident or (s.code is not None and str(s.code) == str(ident)):
                return s
        return None

    def buscar_curso(self, code):
        for c in self.courses:
            if str(c.code).lower() == str(code).lower():
                return c
        return None

    def buscar_servidor(self, name):
        for s in self.servers:
            if s.name.lower() == name.lower():
                return s
        return None

    # ---------------- Importar / Exportar ----------------
    def importar(self, filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            self.students = [
                Student(_get(x, "name", "nombre"), _get(x, "mac"), _get(x, "code", "codigo"))
                for x in _get(data, "students", "alumnos", default=[])
            ]

            self.servers = []
            for y in _get(data, "servers", "servidores", default=[]):
                services = [
                    Service(_get(sv, "name", "nombre"),
                            _get(sv, "protocol", "protocolo"),
                            _get(sv, "port", "puerto"))
                    for sv in _get(y, "services", "servicios", default=[])
                ]
                self.servers.append(Server(_get(y, "name", "nombre"), _get(y, "ip"), services))

            self.courses = []
            for z in _get(data, "courses", "cursos", default=[]):
                servers = [
                    {"name": _get(s, "name", "nombre"),
                     "allowed_services": list(_get(s, "allowed_services", "servicios_permitidos", default=[]))}
                    for s in _get(z, "servers", "servidores", default=[])
                ]
                self.courses.append(Course(
                    _get(z, "name", "nombre"),
                    _get(z, "code", "codigo"),
                    _get(z, "state", "estado"),
                    list(_get(z, "students", "alumnos", default=[])),
                    servers,
                ))

            print(f"¡Éxito! Datos cargados: {len(self.students)} alumnos, "
                  f"{len(self.courses)} cursos, {len(self.servers)} servidores.")
        except FileNotFoundError:
            print(f"[ERROR] No se encontró el archivo '{filename}'.")
        except Exception as e:
            print(f"[ERROR] Ocurrió un problema al leer el YAML: {e}")

    def exportar(self, filename):
        data = {
            "students": [
                {k: v for k, v in (("name", s.name), ("code", s.code), ("mac", s.mac)) if v is not None}
                for s in self.students
            ],
            "courses": [
                {"name": c.name, "code": c.code, "state": c.state,
                 "students": c.students, "servers": c.servers}
                for c in self.courses
            ],
            "servers": [
                {"name": s.name, "ip": s.ip,
                 "services": [{"name": sv.name, "protocol": sv.protocol, "port": sv.port} for sv in s.services]}
                for s in self.servers
            ],
        }
        try:
            with open(filename, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            print(f"Datos exportados a '{filename}'.")
        except Exception as e:
            print(f"[ERROR] No se pudo exportar: {e}")

    # ---------------- Cursos ----------------
    def listar_cursos(self):
        print("\n--- Lista de Cursos ---")
        if not self.courses:
            print("No hay cursos cargados.")
        for c in self.courses:
            print(f"[{c.code}] {c.name} - Estado: {c.state}")

    def mostrar_detalles_curso(self, code):
        c = self.buscar_curso(code)
        if not c:
            print("Curso no encontrado.")
            return
        print(f"\n--- Detalles del Curso: {c.name} ---")
        print(f"Código: {c.code}\nEstado: {c.state}")
        print("Alumnos matriculados:")
        if not c.students:
            print("  (ninguno)")
        for ident in c.students:
            s = self.buscar_alumno(ident)
            if s:
                print(f"  - {s.name} | MAC: {s.mac}")
            else:
                print(f"  - {ident} (no registrado en alumnos)")
        print("Servidores asignados:")
        for s in c.servers:
            print(f"  - {s['name']} (Servicios permitidos: {', '.join(s['allowed_services'])})")

    def gestionar_alumnos_curso(self, code, action, student_ident):
        c = self.buscar_curso(code)
        if not c:
            print("Curso no encontrado.")
            return
        s = self.buscar_alumno(student_ident)
        if not s:
            print("Alumno no encontrado.")
            return
        if action.lower() == "agregar":
            if c.agregar_alumno(s):
                print(f"Alumno '{s.name}' agregado al curso {c.code}.")
            else:
                print("El alumno ya está en el curso.")
        elif action.lower() == "eliminar":
            if c.remover_alumno(s):
                print(f"Alumno '{s.name}' eliminado del curso {c.code}.")
            else:
                print("El alumno no pertenece a este curso.")
        else:
            print("Acción inválida (use 'agregar' o 'eliminar').")

    # ---------------- Alumnos ----------------
    def crear_alumno(self, name, mac, code=None):
        if self.buscar_alumno(name):
            print("Ya existe un alumno con ese nombre.")
            return
        self.students.append(Student(name, mac.lower(), code or None))
        print(f"Alumno {name} creado con éxito.")

    def listar_alumnos(self, filtro_nombre=None, filtro_curso=None):
        print("\n--- Lista de Alumnos ---")
        curso = None
        if filtro_curso:
            curso = self.buscar_curso(filtro_curso)
            if not curso:
                print("Curso no encontrado.")
                return
        encontrados = 0
        for s in self.students:
            if filtro_nombre and filtro_nombre.lower() not in s.name.lower():
                continue
            if curso and not curso.tiene_alumno(s):
                continue
            codigo = f" | Código: {s.code}" if s.code is not None else ""
            print(f"Nombre: {s.name}{codigo} | MAC: {s.mac}")
            encontrados += 1
        if encontrados == 0:
            print("No se encontraron alumnos.")

    def mostrar_detalles_alumno(self, ident):
        s = self.buscar_alumno(ident)
        if not s:
            print("Alumno no encontrado.")
            return
        print("\n--- Detalles del Alumno ---")
        print(f"Código: {s.code if s.code is not None else '-'}\nNombre: {s.name}\nMAC: {s.mac}")
        cursos = [c.name for c in self.courses if c.tiene_alumno(s)]
        print(f"Cursos matriculados: {', '.join(cursos) if cursos else 'Ninguno'}")

    # ---------------- Servidores ----------------
    def listar_servidores(self):
        print("\n--- Lista de Servidores ---")
        if not self.servers:
            print("No hay servidores cargados.")
        for s in self.servers:
            print(f"Nombre: {s.name} | IP: {s.ip}")

    def mostrar_servicios_servidor(self, server_name):
        s = self.buscar_servidor(server_name)
        if not s:
            print("Servidor no encontrado.")
            return
        print(f"\n--- Servicios de {s.name} ({s.ip}) ---")
        for sv in s.services:
            print(f"  - {sv.name} ({sv.protocol} puerto {sv.port})")

    # ---------------- Conexiones ----------------
    def crear_conexion(self, student_ident, course_code, server_name, service_name):
        # 1. Validaciones de la política
        alumno = self.buscar_alumno(student_ident)
        if not alumno:
            print("Alumno no encontrado.")
            return
        curso = self.buscar_curso(course_code)
        if not curso:
            print("Curso no encontrado.")
            return
        if not curso.tiene_alumno(alumno):
            print(f"{alumno.name} no está matriculado en {curso.code}. Conexión denegada.")
            return
        if not curso.esta_activo():
            print(f"El curso {curso.code} no está activo (estado: {curso.state}). Conexión denegada.")
            return
        servidor = self.buscar_servidor(server_name)
        if not servidor:
            print("Servidor no encontrado.")
            return
        permitidos = curso.servicios_permitidos(servidor.name)
        if permitidos is None:
            print(f"El servidor {servidor.name} no está asignado al curso {curso.code}. Conexión denegada.")
            return
        if service_name.lower() not in [p.lower() for p in permitidos]:
            print(f"El servicio '{service_name}' no está permitido para el curso {curso.code}. Conexión denegada.")
            return
        servicio = servidor.get_service(service_name)
        if not servicio:
            print(f"El servidor {servidor.name} no ofrece el servicio '{service_name}'.")
            return

        # 2. Ubicar al alumno y al servidor en la red
        try:
            src_dpid, src_port = get_attachment_point(self.controller_ip, mac=alumno.mac)
            dst_dpid, dst_port = get_attachment_point(self.controller_ip, ip=servidor.ip)
        except requests.RequestException as e:
            print(f"[ERROR] No se pudo contactar al controlador: {e}")
            return
        if src_dpid is None:
            print(f"No se encontró el punto de conexión del alumno (MAC {alumno.mac}).")
            return
        if dst_dpid is None:
            print(f"No se encontró el punto de conexión del servidor (IP {servidor.ip}).")
            return

        # 3. Calcular la ruta y crear los flujos
        try:
            route = get_route(self.controller_ip, src_dpid, src_port, dst_dpid, dst_port)
        except requests.RequestException as e:
            print(f"[ERROR] No se pudo obtener la ruta: {e}")
            return
        if not route:
            print("El controlador no devolvió una ruta.")
            return

        handler = uuid.uuid4().hex[:8]
        try:
            flows = build_route(self.controller_ip, handler, route,
                                alumno.mac, servidor.ip, servicio.protocol, servicio.port)
        except Exception as e:
            print(f"[ERROR] No se pudieron instalar los flujos: {e}")
            return

        self.connections[handler] = {
            "student": alumno.name,
            "student_mac": alumno.mac,
            "server": servidor.name,
            "server_ip": servidor.ip,
            "service": servicio.name,
            "course": curso.code,
            "route": route,
            "flows": flows,
        }
        print(f"Conexión creada. Handler: {handler} ({len(flows)} flujos instalados)")

    def listar_conexiones(self):
        print("\n--- Conexiones Activas ---")
        if not self.connections:
            print("No hay conexiones activas.")
            return
        for handler, info in self.connections.items():
            print(f"[{handler}] Alumno: {info['student']} ({info['student_mac']}) <--> "
                  f"Servidor: {info['server']} ({info['server_ip']}) | "
                  f"Servicio: {info['service']} | Curso: {info['course']}")

    def borrar_conexion(self, handler):
        info = self.connections.get(handler)
        if not info:
            print("Handler no encontrado.")
            return
        for flow_name in info["flows"]:
            try:
                delete_flow(self.controller_ip, flow_name)
            except requests.RequestException as e:
                print(f"[AVISO] No se pudo borrar el flujo {flow_name}: {e}")
        del self.connections[handler]
        print(f"Conexión {handler} eliminada correctamente.")


# =====================================================================
#                      FUNCIONES DE FLOODLIGHT
# =====================================================================
def get_attachment_point(controller_ip, mac=None, ip=None):
    """Devuelve (DPID, puerto) del switch al que está conectado un host (por MAC o por IP)."""
    url = f'http://{controller_ip}:8080/wm/device/'
    params = {'mac': mac} if mac else {'ipv4': ip}
    data = requests.get(url, params=params, timeout=5).json()
    if isinstance(data, dict):  # algunas versiones devuelven {"devices": [...]}
        data = data.get("devices", [])
    for device in data:
        aps = device.get("attachmentPoint", [])
        if aps:
            return aps[0]["switchDPID"], aps[0]["port"]
    return None, None


def get_route(controller_ip, src_dpid, src_port, dst_dpid, dst_port):
    url = (f'http://{controller_ip}:8080/wm/topology/route/'
           f'{src_dpid}/{src_port}/{dst_dpid}/{dst_port}/json')
    return requests.get(url, timeout=5).json()


def _port_number(p):
    if isinstance(p, dict):
        return p.get("portNumber", p.get("shortPortNumber"))
    return p


def push_flow(controller_ip, flow):
    url = f'http://{controller_ip}:8080/wm/staticflowpusher/json'
    r = requests.post(url, json=flow, timeout=5)
    r.raise_for_status()


def delete_flow(controller_ip, flow_name):
    url = f'http://{controller_ip}:8080/wm/staticflowpusher/json'
    requests.delete(url, json={"name": flow_name}, timeout=5)


def build_route(controller_ip, handler, route, student_mac, server_ip, protocol, port):
    """
    La ruta viene como pares [switch, puerto_entrada], [switch, puerto_salida], ...
    En cada switch se instalan flujos de ida y vuelta para el servicio, más ARP.
    Devuelve la lista de nombres de flujos instalados (para poder borrarlos luego).
    """
    proto = str(protocol).upper()
    ip_proto = "0x06" if proto == "TCP" else "0x11"
    l4 = "tcp" if proto == "TCP" else "udp"

    hops = [(h["switch"], _port_number(h["port"])) for h in route]
    flows = []

    for i in range(0, len(hops) - 1, 2):
        sw, in_port = hops[i]
        _, out_port = hops[i + 1]
        n = i // 2
        base = {"switch": sw, "priority": "100", "active": "true"}

        entries = [
            # Alumno -> Servidor (servicio)
            {**base, "name": f"{handler}_{n}_ida", "in_port": str(in_port),
             "eth_type": "0x0800", "eth_src": student_mac, "ipv4_dst": server_ip,
             "ip_proto": ip_proto, f"{l4}_dst": str(port), "actions": f"output={out_port}"},
            # Servidor -> Alumno (respuesta)
            {**base, "name": f"{handler}_{n}_vuelta", "in_port": str(out_port),
             "eth_type": "0x0800", "eth_dst": student_mac, "ipv4_src": server_ip,
             "ip_proto": ip_proto, f"{l4}_src": str(port), "actions": f"output={in_port}"},
            # ARP en ambos sentidos
            {**base, "name": f"{handler}_{n}_arp_ida", "in_port": str(in_port),
             "eth_type": "0x0806", "eth_src": student_mac, "actions": f"output={out_port}"},
            {**base, "name": f"{handler}_{n}_arp_vuelta", "in_port": str(out_port),
             "eth_type": "0x0806", "eth_dst": student_mac, "actions": f"output={in_port}"},
        ]
        for flow in entries:
            push_flow(controller_ip, flow)
            flows.append(flow["name"])

    return flows


# =====================================================================
#                               MENÚ
# =====================================================================
def menu(manager):
    while True:
        try:
            option = int(input(
                "\n################################################\n"
                "Network Policy manager de la UPSM\n"
                "################################################\n\n"
                "Seleccione una opción:\n\n"
                "1) Importar\n"
                "2) Exportar\n"
                "3) Cursos\n"
                "4) Alumnos\n"
                "5) Servidores\n"
                "6) Políticas\n"
                "7) Conexiones\n"
                "8) Salir\n"
                ">>> "
            ))
        except ValueError:
            print("Entrada inválida.")
            continue

        match option:
            case 1:
                nombre = input("Nombre de archivo (Enter = database.yaml): ").strip() or "database.yaml"
                manager.importar(nombre)
            case 2:
                nombre = input("Nombre de archivo (Enter = export.yaml): ").strip() or "export.yaml"
                manager.exportar(nombre)
            case 3:
                print("\n1) Listar\n2) Mostrar detalles\n3) Gestionar alumnos")
                sub = input(">>> ")
                if sub == '1':
                    manager.listar_cursos()
                elif sub == '2':
                    manager.mostrar_detalles_curso(input("Código del curso: "))
                elif sub == '3':
                    codigo = input("Código del curso: ")
                    accion = input("Acción (agregar/eliminar): ")
                    alumno = input("Nombre o código del alumno: ")
                    manager.gestionar_alumnos_curso(codigo, accion, alumno)
            case 4:
                print("\n1) Crear\n2) Listar\n3) Mostrar detalles")
                sub = input(">>> ")
                if sub == '1':
                    nombre = input("Nombre: ")
                    mac = input("MAC: ")
                    codigo = input("Código (opcional): ").strip()
                    manager.crear_alumno(nombre, mac, codigo)
                elif sub == '2':
                    f_nombre = input("Filtrar por nombre (Enter = sin filtro): ").strip()
                    f_curso = input("Filtrar por código de curso (Enter = sin filtro): ").strip()
                    manager.listar_alumnos(f_nombre or None, f_curso or None)
                elif sub == '3':
                    manager.mostrar_detalles_alumno(input("Nombre o código del alumno: "))
            case 5:
                print("\n1) Listar\n2) Mostrar servicios")
                sub = input(">>> ")
                if sub == '1':
                    manager.listar_servidores()
                elif sub == '2':
                    manager.mostrar_servicios_servidor(input("Nombre del servidor: "))
            case 6:
                print("Opción no implementada (no es requerida).")
            case 7:
                print("\n1) Crear\n2) Listar\n3) Borrar")
                sub = input(">>> ")
                if sub == '1':
                    alumno = input("Nombre o código del alumno: ")
                    curso = input("Código del curso: ")
                    servidor = input("Nombre del servidor: ")
                    servicio = input("Servicio (ej: ssh): ")
                    manager.crear_conexion(alumno, curso, servidor, servicio)
                elif sub == '2':
                    manager.listar_conexiones()
                elif sub == '3':
                    manager.borrar_conexion(input("Handler: ").strip())
            case 8:
                print("Saliendo del sistema...")
                break
            case _:
                print("Opción inválida.")


def main():
    manager = NetworkPolicyManager()
    menu(manager)


if __name__ == "__main__":
    main()