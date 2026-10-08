import yaml
import json
import uuid
import asyncio
import requests

CONTROLLER_IP = '192.168.0.10'  # IP del controlador Floodlight


def _get(d, *keys, default=None):
    # Lee un campo del YAML (acepta nombre en inglés o español)
    for k in keys:
        if k in d:
            return d[k]
    return default


# ----- Clases -----
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
        self.services = services

    # Busca un servicio por nombre
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
        self.students = students if students is not None else []
        self.servers = servers if servers is not None else []

    # ¿El alumno está matriculado?
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

    # Servicios que el curso permite en un servidor (None si no lo tiene)
    def servicios_permitidos(self, server_name):
        for s in self.servers:
            if s["name"] == server_name:
                return s["allowed_services"]
        return None

    def esta_activo(self):
        return str(self.state).upper() in ("DICTANDO", "ACTIVO", "ACTIVE")


# ----- Gestor principal -----
class NetworkPolicyManager:
    def __init__(self):
        self.students = []
        self.servers = []
        self.courses = []
        self.connections = {}  # conexiones activas, por handler
        self.controller_ip = CONTROLLER_IP

    # Búsquedas
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

    # Importar / Exportar
    # Carga alumnos, servidores y cursos desde el YAML
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

    # Guarda los datos actuales en un YAML
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

    # Cursos
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

    # Alumnos
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

    # Servidores
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

    # Políticas
    # Muestra los cursos que permiten un servicio en un servidor
    def cursos_con_acceso(self, server_name, service_name):
        servidor = self.buscar_servidor(server_name)
        if not servidor:
            print("Servidor no encontrado.")
            return
        print(f"\n--- Cursos con acceso a '{service_name}' en {servidor.name} ({servidor.ip}) ---")
        encontrados = 0
        for c in self.courses:
            permitidos = c.servicios_permitidos(servidor.name)
            if permitidos and service_name.lower() in [p.lower() for p in permitidos]:
                nota = "" if c.esta_activo() else "  <- inactivo, no otorga acceso"
                print(f"[{c.code}] {c.name} - Estado: {c.state}{nota}")
                encontrados += 1
        if encontrados == 0:
            print("Ningún curso tiene acceso a ese servicio.")

    # Conexiones
    def crear_conexion(self, student_ident, course_code, server_name, service_name):
        # 1) Verificar que el alumno esté autorizado
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

        # 2) Ver en qué switch y puerto están el alumno y el servidor
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

        # 3) Pedir la ruta al controlador e instalar los flows
        try:
            route = get_route(self.controller_ip, src_dpid, src_port, dst_dpid, dst_port)
        except requests.RequestException as e:
            print(f"[ERROR] No se pudo obtener la ruta: {e}")
            return
        if not route:
            print("El controlador no devolvió una ruta.")
            return

        handler = uuid.uuid4().hex[:8]  # ID corto para la conexión
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
            print("  Ruta:", json.dumps(info["route"], indent=4))

    def borrar_conexion(self, handler):
        info = self.connections.get(handler)
        if not info:
            print("Handler no encontrado.")
            return
        # Borra todos los flows de la conexión en paralelo
        resultados = asyncio.run(_delete_flows_async(self.controller_ip, info["flows"]))
        for flow_name, r in zip(info["flows"], resultados):
            if isinstance(r, Exception):
                print(f"[AVISO] No se pudo borrar el flujo {flow_name}: {r}")
        del self.connections[handler]
        print(f"Conexión {handler} eliminada correctamente.")


# ----- Funciones que hablan con Floodlight -----
def get_attachment_point(controller_ip, mac=None, ip=None):
    # Devuelve el switch (DPID) y puerto donde está conectado un host
    url = f'http://{controller_ip}:8080/wm/device/'
    params = {'mac': mac} if mac else {'ipv4': ip}
    data = requests.get(url, params=params, timeout=5).json()
    if isinstance(data, dict):
        data = data.get("devices", [])
    for device in data:
        aps = device.get("attachmentPoint", [])
        if aps:
            return aps[0]["switchDPID"], aps[0]["port"]
    return None, None


# Pide al controlador la ruta entre dos puntos de la red
def get_route(controller_ip, src_dpid, src_port, dst_dpid, dst_port):
    url = (f'http://{controller_ip}:8080/wm/topology/route/'
           f'{src_dpid}/{src_port}/{dst_dpid}/{dst_port}/json')
    data = requests.get(url, timeout=5).json()
    if isinstance(data, dict):
        data = data.get("results", [])
    return data


# Saca el número de puerto (a veces viene dentro de un dict)
def _port_number(p):
    if isinstance(p, dict):
        return p.get("portNumber", p.get("shortPortNumber"))
    return p


# Instala un flow en un switch
def push_flow(controller_ip, flow):
    url = f'http://{controller_ip}:8080/wm/staticflowpusher/json'
    r = requests.post(url, json=flow, timeout=5)
    r.raise_for_status()


# Borra un flow por su nombre
def delete_flow(controller_ip, flow_name):
    url = f'http://{controller_ip}:8080/wm/staticflowpusher/json'
    requests.delete(url, json={"name": flow_name}, timeout=5)


# Crea los flows de la ruta: en cada switch, ida y vuelta del servicio + ARP
def build_route(controller_ip, handler, route, student_mac, server_ip, protocol, port):
    proto = str(protocol).upper()
    ip_proto = "0x06" if proto == "TCP" else "0x11"  # 6 = TCP, 17 = UDP
    l4 = "tcp" if proto == "TCP" else "udp"

    # La ruta viene en pares: (switch, puerto de entrada), (switch, puerto de salida)
    hops = [(h["switch"], _port_number(h["port"])) for h in route]
    all_entries = []

    for i in range(0, len(hops) - 1, 2):
        sw, in_port = hops[i]
        _, out_port = hops[i + 1]
        n = i // 2
        base = {"switch": sw, "priority": "100", "active": "true"}

        entries = [
            # Ida: alumno -> servidor
            {**base, "name": f"{handler}_{n}_ida", "in_port": str(in_port),
             "eth_type": "0x0800", "eth_src": student_mac, "ipv4_dst": server_ip,
             "ip_proto": ip_proto, f"{l4}_dst": str(port), "actions": f"output={out_port}"},
            # Vuelta: servidor -> alumno
            {**base, "name": f"{handler}_{n}_vuelta", "in_port": str(out_port),
             "eth_type": "0x0800", "eth_dst": student_mac, "ipv4_src": server_ip,
             "ip_proto": ip_proto, f"{l4}_src": str(port), "actions": f"output={in_port}"},
            # ARP de ida y de vuelta
            {**base, "name": f"{handler}_{n}_arp_ida", "in_port": str(in_port),
             "eth_type": "0x0806", "eth_src": student_mac, "actions": f"output={out_port}"},
            {**base, "name": f"{handler}_{n}_arp_vuelta", "in_port": str(out_port),
             "eth_type": "0x0806", "eth_dst": student_mac, "actions": f"output={in_port}"},
        ]
        all_entries.extend(entries)

    # Se envían todos los flows a la vez (asíncrono)
    asyncio.run(_push_flows_async(controller_ip, all_entries))
    return [f["name"] for f in all_entries]


# Instala varios flows en paralelo
async def _push_flows_async(controller_ip, entries):
    tareas = [asyncio.to_thread(push_flow, controller_ip, flow) for flow in entries]
    resultados = await asyncio.gather(*tareas, return_exceptions=True)
    errores = [r for r in resultados if isinstance(r, Exception)]
    if errores:
        raise errores[0]


# Borra varios flows en paralelo
async def _delete_flows_async(controller_ip, flow_names):
    tareas = [asyncio.to_thread(delete_flow, controller_ip, name) for name in flow_names]
    return await asyncio.gather(*tareas, return_exceptions=True)


# ----- Menú -----
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
                print("\n1) Cursos con acceso a un servicio")
                sub = input(">>> ")
                if sub == '1':
                    servidor = input("Nombre del servidor: ")
                    servicio = input("Servicio (ej: ssh): ")
                    manager.cursos_con_acceso(servidor, servicio)
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