import os
import re
import time
import argparse
import sys
from urllib.parse import urljoin

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# --- Configurações ---
BASE_URL = "https://www.estrategiaconcursos.com.br"
MY_COURSES_URL = urljoin(BASE_URL, "/app/dashboard/cursos")


# --- Funções Auxiliares ---

def sanitize_filename(original_filename):
    """
    Remove caracteres inválidos de um nome de arquivo/diretório para garantir
    compatibilidade com o sistema de arquivos.
    """
    # Remove caracteres inválidos do Windows e outros sistemas
    sanitized = re.sub(r'[<>:"/\\|?*]', '', original_filename)
    # Remove pontos e vírgulas para nomes mais limpos
    sanitized = re.sub(r'[.,]', '', sanitized)
    # Substitui espaços e hífens múltiplos por um único underscore
    sanitized = re.sub(r'[\s-]+', '_', sanitized)
    # Remove underscores, pontos ou hífens no início ou fim
    sanitized = sanitized.strip('._- ')

    return sanitized.strip()


def download_file(url, file_path, current_page_url=None):
    """
    Realiza o download de um arquivo usando a biblioteca requests, com
    cabeçalhos adequados e tratamento de erros.
    """
    print(f"   Tentando baixar: {os.path.basename(file_path)}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7'
    }
    # O cabeçalho 'Referer' pode ser crucial para evitar erros de acesso negado (403 Forbidden)
    if current_page_url:
        headers['Referer'] = current_page_url

    try:
        response = requests.get(url, stream=True, timeout=60, headers=headers)
        response.raise_for_status()  # Lança uma exceção para códigos de erro HTTP (4xx ou 5xx)

        # Verifica se o arquivo não é suspeitamente pequeno (pode ser uma página de erro)
        content_length = response.headers.get('content-length')
        if content_length and int(content_length) < 1024:
            print(f"     AVISO: Conteúdo suspeitamente pequeno ({content_length} bytes). Pode ser uma página de erro.")

        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"     Baixado com sucesso: {os.path.basename(file_path)}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"     Erro ao baixar {os.path.basename(file_path)} de {url}: {e}")
        return False
    except Exception as e:
        print(f"     Erro inesperado ao baixar {os.path.basename(file_path)}: {e}")
        return False


def handle_popups(driver):
    """Tenta fechar popups conhecidos que podem interceptar cliques."""
    print("        Verificando e lidando com popups/overlays...")
    try:
        # Espera por um elemento específico do popup
        getsitecontrol_widget = WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.ID, "getsitecontrol-44266"))
        )
        print("        Widget 'getsitecontrol' detectado. Tentando fechar via JavaScript.")
        # Usa JavaScript para esconder o elemento, uma tática mais robusta que cliques
        driver.execute_script("arguments[0].style.display = 'none';", getsitecontrol_widget)
        time.sleep(1)
    except TimeoutException:
        print("        Nenhum popup 'getsitecontrol' detectado.")
    except Exception as e:
        print(f"        Erro inesperado ao lidar com popups: {e}")


def get_course_data(driver):
    """Navega até a página 'Minhas Matrículas' e extrai os links e títulos dos cursos."""
    print("Navegando para a página 'Meus Cursos'...")
    driver.get(MY_COURSES_URL)

    try:
        # Espera até que os cards dos cursos estejam presentes na página
        WebDriverWait(driver, 30).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "section[id^='card'] a.sc-cHGsZl"))
        )
        time.sleep(3)  # Pausa adicional para garantir que tudo carregou

        course_elements = driver.find_elements(By.CSS_SELECTOR, "section[id^='card']")
        courses = []
        for course_elem in course_elements:
            try:
                link_elem = course_elem.find_element(By.CSS_SELECTOR, "a.sc-cHGsZl")
                title_elem = course_elem.find_element(By.CSS_SELECTOR, "h1.sc-ksYbfQ")
                course_href = link_elem.get_attribute('href')
                course_title = title_elem.text
                if course_href and course_title:
                    courses.append({"title": course_title, "url": course_href})
            except (NoSuchElementException, StaleElementReferenceException):
                print("   Elemento de curso não encontrado ou obsoleto. Pulando.")
        print(f"Encontrados {len(courses)} cursos.")
        return courses
    except TimeoutException:
        print("Erro: Tempo esgotado ao carregar a lista de cursos.")
        return []


def get_lesson_data(driver, course_url):
    """
    Navega para a página de um curso e extrai os links, títulos e subtítulos das aulas.
    """
    print(f"   Navegando para a página do curso: {course_url}")
    driver.get(course_url)

    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.LessonList-item a.Collapse-header"))
        )
        time.sleep(3)

        lesson_elements = driver.find_elements(By.CSS_SELECTOR, "div.LessonList-item")
        lessons = []
        for lesson_elem in lesson_elements:
            try:
                # Pula aulas desabilitadas
                if "isDisabled" in lesson_elem.get_attribute("class"):
                    continue

                link_elem = lesson_elem.find_element(By.CSS_SELECTOR, "a.Collapse-header")
                title_h2_elem = lesson_elem.find_element(By.CSS_SELECTOR, "h2.SectionTitle")
                lesson_title = title_h2_elem.text

                lesson_subtitle = ""
                try:
                    title_p_elem = lesson_elem.find_element(By.CSS_SELECTOR, "p.sc-gZMcBi")
                    lesson_subtitle = title_p_elem.text
                except NoSuchElementException:
                    pass  # É normal não haver subtítulo

                lesson_href = link_elem.get_attribute('href')
                if lesson_href and lesson_title:
                    lessons.append({
                        "title": lesson_title,
                        "subtitle": lesson_subtitle,
                        "url": lesson_href
                    })
            except (NoSuchElementException, StaleElementReferenceException):
                print("    Elemento da aula não encontrado ou obsoleto. Pulando.")
        print(f"    Encontradas {len(lessons)} aulas disponíveis.")
        return lessons
    except TimeoutException:
        print("   Erro: Tempo esgotado ao carregar a lista de aulas.")
        return []


def download_lesson_materials(driver, lesson_info, course_title, download_dir):
    """
    Navega para a página de uma aula, salva o subtítulo e baixa os materiais.
    """
    lesson_title = lesson_info['title']
    lesson_subtitle = lesson_info['subtitle']
    lesson_url = lesson_info['url']

    print(f"       Processando aula: {lesson_title}")
    driver.get(lesson_url)

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.Lesson-contentTop, div.LessonVideos"))
        )
        time.sleep(2)
    except TimeoutException:
        print(f"       Erro: Tempo esgotado ao carregar a página da aula '{lesson_title}'. Pulando.")
        return

    handle_popups(driver)

    sanitized_course_title = sanitize_filename(course_title)
    sanitized_lesson_title = sanitize_filename(lesson_title)

    # Usa o diretório de download fornecido como argumento
    lesson_download_path = os.path.join(download_dir, sanitized_course_title, sanitized_lesson_title)

    try:
        os.makedirs(lesson_download_path, exist_ok=True)
    except OSError as e:
        print(f"       ERRO CRÍTICO ao criar diretório: {e}")
        return

    # Salva o subtítulo em um arquivo de texto
    if lesson_subtitle:
        subjects_file_path = os.path.join(lesson_download_path, "Assuntos_dessa_aula.txt")
        if not os.path.exists(subjects_file_path):
            try:
                with open(subjects_file_path, 'w', encoding='utf-8') as f:
                    f.write(lesson_subtitle)
                print(f"       Arquivo 'Assuntos_dessa_aula.txt' criado.")
            except Exception as e:
                print(f"       Erro ao criar 'Assuntos_dessa_aula.txt': {e}")

    # Baixa Livros Eletrônicos (PDFs)
    print("       Procurando por Livros Eletrônicos (PDFs)...")
    try:
        pdf_links = driver.find_elements(By.XPATH,
                                         "//a[contains(@class, 'LessonButton') and .//i[contains(@class, 'icon-file')]]")
        for pdf_link in pdf_links:
            pdf_url = pdf_link.get_attribute('href')
            if not pdf_url or "api.estrategiaconcursos.com.br" not in pdf_url:
                continue

            pdf_text_raw = "original"
            try:
                version_text_element = pdf_link.find_element(By.CSS_SELECTOR, "span.LessonButton-text > span")
                pdf_text_raw = version_text_element.text.strip()
            except NoSuchElementException:
                pass  # Mantém "original" se não encontrar texto específico

            filename_suffix = "_" + sanitize_filename(pdf_text_raw)
            filename = f"{sanitized_lesson_title}_Livro_Eletronico{filename_suffix}.pdf"
            full_file_path = os.path.join(lesson_download_path, filename)

            if os.path.exists(full_file_path):
                print(f"       PDF '{filename}' já existe. Pulando.")
            else:
                print(f"       Encontrado PDF: {pdf_text_raw}")
                download_file(pdf_url, full_file_path, driver.current_url)
    except Exception as e:
        print(f"       Erro ao processar PDFs: {e}")

    # Baixa todos os Vídeos da Playlist
    print("       Procurando por Vídeos...")
    try:
        playlist_items = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.ListVideos-items-video a.VideoItem"))
        )

        videos_to_download = []
        for item in playlist_items:
            video_href = item.get_attribute('href')
            video_title = item.find_element(By.CSS_SELECTOR, "span.VideoItem-info-title").text
            if video_href and video_title:
                videos_to_download.append({'url': video_href, 'title': video_title})

        if not videos_to_download:
            print("       Nenhum vídeo encontrado na playlist.")
            return

        print(f"       Encontrados {len(videos_to_download)} vídeos. Iniciando downloads...")

        for i, video_info in enumerate(videos_to_download):
            print(f"\n        Processando vídeo {i + 1}/{len(videos_to_download)}: {video_info['title']}")
            driver.get(video_info['url'])
            time.sleep(2)

            # Baixar PDFs específicos do vídeo (Resumo, Slides, etc.)
            print(f"          Procurando por PDFs específicos do vídeo '{video_title}'...")
            video_pdf_types = {
                "Baixar Resumo": f"_Resumo_{i}.pdf",
                "Baixar Slides": f"_Slides_Video_{i}.pdf",  # Differentiate from general slides
                "Baixar Mapa Mental": f"_Mapa_Mental_{i}.pdf"
            }

            for pdf_button_text, filename_suffix in video_pdf_types.items():
                try:
                    # Find the link that contains the specific text
                    pdf_link_elem = driver.find_element(By.XPATH,
                                                        f"//a[contains(@class, 'LessonButton') and .//span[contains(text(), '{pdf_button_text}')]]")
                    pdf_url = pdf_link_elem.get_attribute('href')

                    if pdf_url:
                        filename = f"{sanitized_lesson_title}_{sanitize_filename(video_title)}{filename_suffix}"
                        full_file_path = os.path.join(lesson_download_path, filename)

                        if os.path.exists(full_file_path):
                            print(
                                f"          PDF '{filename_suffix.replace('.pdf', '')}' para este vídeo já existe no disco. Pulando.")
                        else:
                            print(f"          Encontrado {pdf_button_text} para o vídeo '{video_title}'.")
                            download_file(pdf_url, full_file_path, driver.current_url)
                    else:
                        print(
                            f"          {pdf_button_text} para o vídeo '{video_title}' encontrado, mas sem URL.")
                except NoSuchElementException:
                    print(f"          {pdf_button_text} não encontrado para o vídeo '{video_title}'.")
                except Exception as e:
                    print(
                        f"          Erro ao processar '{pdf_button_text}' para o vídeo '{video_title}': {e}")

            try:
                # Expande a seção "Opções de download" se estiver fechada
                download_options_header = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//div[contains(@class, 'Collapse-header')]//strong[text()='Opções de download']"))
                )
                header_container = download_options_header.find_element(By.XPATH,
                                                                        "./ancestor::div[contains(@class, 'Collapse-header-container')]")
                collapse_body = header_container.find_element(By.XPATH, "./following-sibling::div")

                if not collapse_body.is_displayed():
                    driver.execute_script("arguments[0].click();", download_options_header)
                    WebDriverWait(driver, 5).until(EC.visibility_of(collapse_body))

                sanitized_video_title = sanitize_filename(video_info['title'])
                preferred_qualities = ["720p", "480p", "360p"]
                downloaded_successfully = False

                for quality in preferred_qualities:
                    filename = f"{sanitized_video_title}_Video_{quality}.mp4"
                    full_file_path = os.path.join(lesson_download_path, filename)

                    if os.path.exists(full_file_path):
                        print(f"          Vídeo '{filename}' já existe. Pulando.")
                        downloaded_successfully = True
                        break

                    try:
                        video_link_elem = collapse_body.find_element(By.XPATH, f".//a[contains(text(), '{quality}')]")
                        video_url = video_link_elem.get_attribute('href')
                        print(f"          Tentando baixar vídeo em {quality}...")
                        if download_file(video_url, full_file_path, driver.current_url):
                            downloaded_successfully = True
                            break
                    except NoSuchElementException:
                        continue  # Tenta a próxima qualidade

                if not downloaded_successfully:
                    print(
                        f"          AVISO: Não foi possível baixar nenhuma qualidade para o vídeo '{video_info['title']}'.")

            except TimeoutException:
                print(
                    f"        Não foi possível encontrar/expandir 'Opções de download' para o vídeo '{video_info['title']}'.")
            except Exception as e:
                print(f"        Erro ao baixar o vídeo '{video_info['title']}': {e}")

    except TimeoutException:
        print("       Nenhuma playlist de vídeos encontrada nesta aula.")
    except Exception as e:
        print(f"       Erro geral ao processar a playlist de vídeos: {e}")


# --- Função de Login ---
def login(driver, wait_time):
    """
    Função para login. Atualmente, está configurada para uma pausa,
    permitindo que o usuário faça o login manualmente.
    """
    print("Navegando para a página de login...")
    driver.get("https://perfil.estrategia.com/login")

    print("=" * 60)
    print("AÇÃO NECESSÁRIA: FAÇA O LOGIN MANUALMENTE NO NAVEGADOR ABERTO")
    print(f"O script ficará pausado por {wait_time} segundos para você completar o login.")
    print("Após o login, o script continuará automaticamente.")
    print("NÃO feche o navegador.")
    print("=" * 60)

    time.sleep(wait_time)

    print("Pausa para login concluída. Continuando o script...")


# --- Fluxo Principal ---
def run_downloader(download_dir, login_wait_time):
    """
    Função principal que orquestra todo o processo de download.
    """
    # Garante que o diretório de download de base exista
    try:
        os.makedirs(download_dir, exist_ok=True)
        print(f"Diretório de download configurado para: {os.path.abspath(download_dir)}")
    except OSError as e:
        print(f"ERRO: Não foi possível criar o diretório de download '{download_dir}'. Erro: {e}")
        sys.exit(1)  # Encerra o script se não puder criar o diretório

    driver = webdriver.Edge()
    driver.maximize_window()

    try:
        login(driver, login_wait_time)

        courses = get_course_data(driver)
        if not courses:
            print("Nenhum curso encontrado ou erro ao carregar a página. Encerrando.")
            return

        for i, course in enumerate(courses):
            print(f"\n[{i + 1}/{len(courses)}] Processando curso: {course['title']}")
            lessons = get_lesson_data(driver, course['url'])

            if not lessons:
                print(f"   Nenhuma aula encontrada para o curso '{course['title']}'. Pulando.")
                continue

            for j, lesson_info in enumerate(lessons):
                print(f"\n    -> Processando aula {j + 1}/{len(lessons)}: {lesson_info['title']}")
                download_lesson_materials(driver, lesson_info, course['title'], download_dir)
                time.sleep(2)

    except Exception as e:
        print(f"\nOcorreu um erro geral no script: {e}")
    finally:
        print("\nProcesso concluído. Fechando o navegador em 10 segundos.")
        time.sleep(10)
        driver.quit()


def main():
    """
    Analisa os argumentos da linha de comando e inicia o processo de download.
    """
    parser = argparse.ArgumentParser(
        description="Baixador de cursos do Estratégia Concursos.",
        formatter_class=argparse.RawTextHelpFormatter  # Melhora a formatação da ajuda
    )

    parser.add_argument(
        '-d', '--dir',                      # Apenas os flags opcionais são listados aqui
        dest='download_dir',                # 'dest' diz ao argparse para salvar o valor em 'args.download_dir'
        metavar='PATH',                     # 'metavar' é o nome que aparece na mensagem de ajuda
        type=str,
        default="E:/Estrategia",            # O valor padrão se o argumento não for fornecido
        help="O caminho completo para a pasta onde os cursos serão salvos.\n(Padrão: E:/Estrategia)"
    )

    parser.add_argument(
        "-w", "--wait-time",
        type=int,
        default=60,
        help="Tempo em segundos para aguardar o login manual (padrão: 60)."
    )

    args = parser.parse_args()

    run_downloader(args.download_dir, args.wait_time)


if __name__ == "__main__":
    main()
