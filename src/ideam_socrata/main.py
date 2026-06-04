import time
import re
import pandas as pd
import copy
from rich.panel import Panel
from rich.align import Align
from rich.prompt import Prompt

# Importaciones locales
from .config import console, CLIENT, DATASETS_INFO, MAPEO_DEPARTAMENTOS, CATALOG_DATASET_ID
from .ui import (espera_estetica, mostrar_tabla_opciones, mostrar_tabla_simple,
                extraer_ids_seleccionados, mostrar_panel_resumen, mostrar_menu_opciones, mostrar_logo)
from .core import intentar, descargar_estandar_por_meses, descargar_especial_directo
from .query_validation import build_department_filter

def main():
    console.clear()
    mostrar_logo()
    console.print(Panel(Align.center(
        "[p_bold]AUTOMATIZACIÓN INTELIGENTE PARA LA GESTIÓN VISUAL DE DATOS HÍDRICOS DEL IDEAM[/p_bold]\n"
        "[bold acento]Proyecto de Tesis de Pregrado – Ingeniería Civil[/bold acento]\n\n"
        "[texto]Autor: [s_bold]Sergio Beltrán Coley[/s_bold]\n"
        "Tutor: [s_bold]Ing. Carol Prada Sánchez[/s_bold]\n"
        "Cotutor: [s_bold]Ing. Sebastián Quintero Merchán[/s_bold]\n\n"
        "Universidad de la Costa – Departamento de Civil y Ambiental\n"
        "Barranquilla, Colombia[/texto]"
    ), border_style="borde", subtitle="[texto_oscuro]PROYECTO DE GRADO - CUC[/texto_oscuro]"))

    # BLOQUE DE CONSENTIMIENTO
    with console.status("[s_bold]Cargando protocolos de investigación...[/s_bold]", spinner="arc"):
        time.sleep(0.5)
    
    terminos = (
        "[s_bold]ACUERDO DE USO ACADÉMICO E INVESTIGATIVO[/s_bold]\n\n"
        "[texto]Esta herramienta automatizada ha sido desarrollada como parte de un proyecto de grado.\n"
        "Al continuar, usted manifiesta estar de acuerdo con los siguientes puntos:\n\n"
        "• El uso de los datos es exclusivamente para [bold acento]fines académicos e investigativos[/bold acento].\n"
        "• La información proviene del [texto]IDEAM[/texto] bajo la Política de Datos Abiertos de Colombia.\n"
        "• El autor no se hace responsable por el tratamiento posterior de la información.\n"
        "• Se prohíbe el uso de esta herramienta para fines comerciales no autorizados.[/texto]"
    )
    console.print(Align.center(Panel(terminos, border_style="primario", title="[p_bold]AVISO LEGAL[/p_bold]", expand=False)))
    
    mostrar_menu_opciones("¿ACEPTA LOS TÉRMINOS PARA INICIAR?", ["Sí, acepto los términos y condiciones", "No acepto (salir)"])
    if Prompt.ask("[s_bold]Elija una opción[/s_bold]", choices=["1", "2"], default="1", show_choices=False, show_default=False) == "2":
        console.print("\n[p_bold][!] Acceso denegado.[/p_bold]\n")
        return
    espera_estetica("Iniciando sistema...")

    while True:
        # PASO 0: SELECCIÓN DE VARIABLE
        mostrar_tabla_simple("VARIABLES DISPONIBLES EN EL SISTEMA", DATASETS_INFO)
        sel_var = Prompt.ask("\n[s_bold]Dígite el número de la variable deseada[/s_bold]", show_default=False).strip()
        espera_estetica("Cargando variable...")
        
        try:
            var_idx = int(sel_var) - 1
            if not (0 <= var_idx < len(DATASETS_INFO)): raise ValueError()
            variable_elegida = DATASETS_INFO[var_idx]
        except:
            console.print("[p_bold]Selección no válida.[/p_bold]")
            continue
            
        dataset_id = variable_elegida["id"]
        col_fecha = variable_elegida["fecha_col"]
        nombre_export_base = variable_elegida['nombre'].replace(" ", "_").replace("(", "").replace(")", "").lower()
        
        paso = 1
        historial = []
        estado = {
            "filtros_base": [], "estaciones_pool": set(), "dict_reemplazo": {},
            "nombre_export": nombre_export_base, "anio_ini": None, "anio_fin": None,
            "resumen": {
                "variable": variable_elegida['nombre'], "deps": "Todos", 
                "zonas": "Todas", "avanzados": {}, "manual": "Ninguna"
            }
        }

        while paso <= 4:
            if paso < 4: mostrar_panel_resumen(estado, paso)
            
            if paso == 1: # DEPARTAMENTOS
                espera_estetica("Accediendo a base de datos territorial...", "earth", 0.4)
                mostrar_menu_opciones("PASO 1: ¿FILTRAR POR DEPARTAMENTO?", ["Sí, seleccionar departamentos", "No, incluir todos", "Atrás (cambiar variable)"])
                res = Prompt.ask("[p_bold]Elija una opción[/p_bold]", choices=["1", "2", "3"], default="2", show_choices=False, show_default=False)
                espera_estetica("Procesando...")
                
                if res == "3": break 
                if res == "1":
                    backup = copy.deepcopy(estado)
                    deps_oficiales = sorted(list(MAPEO_DEPARTAMENTOS.keys()))
                    mostrar_tabla_opciones("DEPARTAMENTOS DISPONIBLES", deps_oficiales)
                    sel = Prompt.ask("[p_bold]Dígite los números deseados[/p_bold]", show_default=False).strip()
                    espera_estetica("Validando selección...")
                    if sel == '0': continue
                    deps_sel = extraer_ids_seleccionados(sel, deps_oficiales)
                    if deps_sel:
                        historial.append(backup)
                        filtro_dep, reemplazos, _variantes = build_department_filter(deps_sel, MAPEO_DEPARTAMENTOS)
                        estado["dict_reemplazo"].update(reemplazos)
                        estado["filtros_base"].append(filtro_dep)
                        estado["resumen"]["deps"] = ", ".join(deps_sel)
                        estado["nombre_export"] += f"_dep_{deps_sel[0][:4]}"
                        paso = 2; continue
                historial.append(copy.deepcopy(estado))
                paso = 2

            elif paso == 2: # FILTROS AVANZADOS
                espera_estetica("Cargando motor de filtros especializados...", "arc", 0.4)
                mostrar_menu_opciones("PASO 2: ¿APLICAR FILTROS ADICIONALES?", ["Sí, configurar filtros avanzados", "No, continuar con selección base", "Atrás (volver a departamentos)"])
                res = Prompt.ask("[p_bold]Elija una opción[/p_bold]", choices=["1", "2", "3"], default="2", show_choices=False, show_default=False)
                espera_estetica("Cargando configuración...")
                
                if res == "3": estado = historial.pop(); paso = 1; continue
                if res == "1":
                    backup = copy.deepcopy(estado)
                    filtros_cat = {
                        "Zona Hidrográfica": "zonahidrografica", "Categoría": "categoria", 
                        "Tecnología": "tecnologia", "Estado": "estado", 
                        "Corriente": "corriente", "Entidad": "entidad", "Municipio": "municipio"
                    }
                    while True:
                        attr_list = list(filtros_cat.keys())
                        opciones_menu = attr_list + ["Ingresar estaciones por código manual", "Finalizar filtros", "Regresar"]
                        mostrar_menu_opciones("CATÁLOGO Y FILTROS AVANZADOS", opciones_menu)
                        sel_attr = Prompt.ask("[bold #A3161A]Elija una opción[/bold #A3161A]", default=str(len(opciones_menu)-1), show_default=False).strip()
                        espera_estetica("Buscando...")
                        
                        if sel_attr == str(len(opciones_menu)): # Regresar
                            estado = historial.pop(); paso = 1; break
                        if sel_attr == str(len(opciones_menu)-1): # Finalizar
                            break
                        
                        if sel_attr == str(len(opciones_menu)-2): # Manual
                            while True:
                                mostrar_menu_opciones("GESTIÓN DE ESTACIONES", ["Escribir códigos directamente", "Ver estaciones filtradas (Ayuda)", "Volver"])
                                sub_res = Prompt.ask("[bold #A3161A]Elija[/bold #A3161A]", choices=["1", "2", "3"], default="1", show_choices=False, show_default=False)
                                espera_estetica("Abriendo gestión...")
                                if sub_res == "3": break
                                if sub_res == "2":
                                    with console.status("[p_bold]Consultando catálogo...[/p_bold]", spinner="earth"):
                                        temp_f = [f.replace("zonahidrografica", "zona_hidrografica").replace("codigoestacion", "codigo") for f in estado["filtros_base"]]
                                        for k, v in estado["resumen"]["avanzados"].items():
                                            c_api = filtros_cat.get(k, k).replace("zonahidrografica", "zona_hidrografica")
                                            valores = ", ".join("'" + x.upper() + "'" for x in v)
                                            temp_f.append(f"upper({c_api}) IN ({valores})")
                                        cat_where = " AND ".join(temp_f) if temp_f else None
                                        est_data = intentar(lambda: CLIENT.get(CATALOG_DATASET_ID, select="codigo, nombre", where=cat_where, order="nombre", limit=50000), "Catálogo")
                                    if est_data:
                                        lista_ayuda = [f"{e['codigo']} - {e['nombre']}" for e in est_data if 'codigo' in e]
                                        mostrar_tabla_opciones("ESTACIONES (CÓDIGO - NOMBRE)", lista_ayuda)
                                        Prompt.ask("\n[s_bold]Presione ENTER para volver[/s_bold]", show_default=False)
                                    continue
                                if sub_res == "1":
                                    cods_input = Prompt.ask("[bold #A3161A]Ingrese códigos (o '0' para volver)[/bold #A3161A]", show_default=False).strip()
                                    espera_estetica("Indexando códigos...")
                                    if cods_input != '0':
                                        lista_c = {c.strip() for c in cods_input.split(",") if c.strip()}
                                        estado["estaciones_pool"].update(lista_c)
                                        estado["resumen"]["manual"] = f"{len(estado['estaciones_pool'])} códigos"
                            continue

                        try:
                            attr_idx = int(sel_attr) - 1
                            attr_name = attr_list[attr_idx]; attr_col = filtros_cat[attr_name]
                            with console.status(f"[p_bold]Buscando {attr_name}...[/p_bold]", spinner="point"):
                                c_cat = attr_col.replace("zonahidrografica", "zona_hidrografica")
                                temp_f = [f.replace("zonahidrografica", "zona_hidrografica").replace("codigoestacion", "codigo") for f in estado["filtros_base"]]
                                cat_where = " AND ".join(temp_f) if temp_f else None
                                opciones = sorted([str(o.get(c_cat)) for o in intentar(lambda: CLIENT.get(CATALOG_DATASET_ID, select=c_cat, where=cat_where, group=c_cat, limit=50000), attr_name) if o.get(c_cat)])
                            if opciones:
                                mostrar_tabla_opciones(f"SELECCIONE {attr_name.upper()}", opciones)
                                sel_val = Prompt.ask("[bold #A3161A]Dígite los números deseados[/bold #A3161A]", show_default=False).strip()
                                espera_estetica("Aplicando filtros...")
                                if sel_val == '0': continue
                                vals_sel = extraer_ids_seleccionados(sel_val, opciones)
                                if vals_sel:
                                    estado["resumen"]["avanzados"][attr_name] = vals_sel
                                    if attr_name == "Zona Hidrográfica": estado["resumen"]["zonas"] = ", ".join(vals_sel)
                        except: pass
                    
                    if estado["resumen"]["avanzados"]:
                        with console.status("[p_bold]Consolidando pool de estaciones...[/p_bold]", spinner="moon"):
                            temp_f = [f.replace("zonahidrografica", "zona_hidrografica").replace("codigoestacion", "codigo") for f in estado["filtros_base"]]
                            for k, v in estado["resumen"]["avanzados"].items():
                                c_api = filtros_cat.get(k, k).replace("zonahidrografica", "zona_hidrografica")
                                valores = ", ".join("'" + x.upper() + "'" for x in v)
                                temp_f.append(f"upper({c_api}) IN ({valores})")
                            cods_enc = {e['codigo'] for e in intentar(lambda: CLIENT.get(CATALOG_DATASET_ID, select="codigo", where=" AND ".join(temp_f), limit=50000), "Pool Final") if 'codigo' in e}
                            estado["estaciones_pool"].update(cods_enc)
                    historial.append(backup)
                    paso = 3; continue
                historial.append(copy.deepcopy(estado))
                paso = 3

            elif paso == 3: # AÑOS
                if col_fecha:
                    with console.status("[s_bold]Obteniendo marco temporal global...[/s_bold]", spinner="clock"):
                        try:
                            res_min = CLIENT.get(dataset_id, select=col_fecha, order=f"{col_fecha} ASC", limit=1)
                            res_max = CLIENT.get(dataset_id, select=col_fecha, order=f"{col_fecha} DESC", limit=1)
                            g_min = int(re.search(r'\d{4}', str(res_min[0].get(col_fecha))).group())
                            g_max = int(re.search(r'\d{4}', str(res_max[0].get(col_fecha))).group())
                        except:
                            g_min, g_max = 1970, pd.Timestamp.now().year

                    mostrar_menu_opciones(f"PASO 3: RANGO DISPONIBLE ({g_min} - {g_max})", ["Usar todo el histórico", "Definir rango personalizado", "Atrás"])
                    res = Prompt.ask("[bold #A3161A]Elija una opción[/bold #A3161A]", choices=["1", "2", "3"], default="1", show_choices=False, show_default=False)
                    espera_estetica("Configurando temporalidad...")
                    
                    if res == "3": estado = historial.pop(); paso = 2; continue
                    if res == "1":
                        estado["anio_ini"], estado["anio_fin"] = g_min, g_max
                    else:
                        backup = copy.deepcopy(estado)
                        try:
                            estado["anio_ini"] = int(Prompt.ask(f"[bold #A3161A]Año INICIO (desde {g_min})[/bold #A3161A]", default=str(g_min), show_default=False))
                            estado["anio_fin"] = int(Prompt.ask(f"[bold #A3161A]Año FIN (hasta {g_max})[/bold #A3161A]", default=str(g_max), show_default=False))
                            historial.append(backup)
                        except: continue
                paso = 4

            elif paso == 4: # FINALIZAR
                mostrar_panel_resumen(estado, paso)
                filtros_fijos = list(estado["filtros_base"])
                est_norm = []
                for c in estado["estaciones_pool"]:
                    est_norm.append(f"'{c}'")
                    if len(c) == 8: est_norm.append(f"'00{c}'")
                
                lista_filtros_api = []
                if est_norm:
                    for i in range(0, len(est_norm), 500):
                        chunk = est_norm[i:i+500]
                        f_set = list(filtros_fijos); f_set.append(f"codigoestacion IN ({', '.join(chunk)})")
                        lista_filtros_api.append(f_set)
                else: lista_filtros_api = [filtros_fijos] if filtros_fijos else [[]]

                if estado["anio_ini"] and estado["anio_fin"]:
                    # Ahora iteramos solo por años. core.py maneja auto-paginación si un año excede 50k.
                    tareas = [(a, None, f_list) for a in range(estado["anio_ini"], estado["anio_fin"] + 1) for f_list in lista_filtros_api]
                else: tareas = [(None, None, f_list) for f_list in lista_filtros_api]
                
                if not tareas:
                    console.print("\n[p_bold][!] Error en rango. Regrese al paso anterior.[/p_bold]")
                    paso = 3; continue

                console.print(f"\n[p_bold]MOTOR LISTO:[/p_bold] [s_bold]{len(tareas)} bloques identificados[/s_bold]")
                mostrar_menu_opciones("¿INICIAR DESCARGA FINAL?", ["Sí, comenzar ahora", "No, volver a años", "Salir"])
                res_fin = Prompt.ask("[bold #A3161A]Elija una opción[/bold #A3161A]", choices=["1", "2", "3"], default="1", show_choices=False, show_default=False)
                espera_estetica("Preparando motor final...")
                
                if res_fin == "1":
                    if not tareas[0][0]: descargar_especial_directo(dataset_id, estado["nombre_export"], variable_elegida["nombre"], lista_filtros_api)
                    else: descargar_estandar_por_meses(dataset_id, col_fecha, tareas, estado["dict_reemplazo"], estado["nombre_export"], variable_elegida["nombre"])
                    break
                elif res_fin == "2": estado = historial.pop(); paso = 3; continue
                else: break

        mostrar_menu_opciones("CONSULTA FINALIZADA", ["Nueva consulta", "Salir"])
        if Prompt.ask("[bold #FCD116]¿Qué desea hacer?[/bold #FCD116]", choices=["1", "2"], default="1", show_choices=False, show_default=False) == "2":
            console.print("\n")
            console.print(Align.center(Panel(
                " [s_bold]Sesión terminada con éxito.[/s_bold]\n"
                " [texto]Proyecto de Grado - Ingeniería Civil CUC.\n\n"
                " [p_bold]© 2025 Sergio Beltrán Coley.[/p_bold][/texto]",
                border_style="borde", 
                title="[p_bold] SALIDA [/p_bold]", 
                expand=False,
                padding=(1, 2)
            )))
            console.print("\n")
            break

if __name__ == "__main__":
    main()
