"""Toolkit-local interface language, independent of Blender's language."""

import bpy
from bpy.props import EnumProperty


_LANGUAGES = (
    ("EN", "English"),
    ("ZH", "简体中文"),
    ("HI", "हिन्दी"),
    ("ES", "Español"),
    ("AR", "العربية"),
    ("FR", "Français"),
    ("HY", "Հայերեն"),
    ("PT_BR", "Português (Brasil)"),
    ("RU", "Русский"),
)
_CODES = ("RU", "ZH", "HI", "ES", "AR", "FR", "HY", "PT_BR")

# English source followed by Russian, Chinese, Hindi, Spanish, Arabic, French,
# Armenian and Brazilian Portuguese. The English source doubles as the fallback.
_STRINGS = """
Language|Язык|语言|भाषा|Idioma|اللغة|Langue|Լեզու|Idioma
Resolution|Разрешение|分辨率|रिज़ॉल्यूशन|Resolución|الدقة|Résolution|Լուծաչափ|Resolução
Custom resolution|Своё разрешение|自定义分辨率|कस्टम रिज़ॉल्यूशन|Resolución personalizada|دقة مخصصة|Résolution personnalisée|Հատուկ լուծաչափ|Resolução personalizada
Width (px)|Ширина (px)|宽度（像素）|चौड़ाई (px)|Ancho (px)|العرض (px)|Largeur (px)|Լայնություն (px)|Largura (px)
Height (px)|Высота (px)|高度（像素）|ऊँचाई (px)|Alto (px)|الارتفاع (px)|Hauteur (px)|Բարձրություն (px)|Altura (px)
Gap (px)|Зазор (px)|间距（像素）|अंतर (px)|Separación (px)|التباعد (px)|Espacement (px)|Միջակայք (px)|Espaçamento (px)
Border (px)|Поле (px)|边距（像素）|किनारे का अंतर (px)|Margen (px)|الهامش (px)|Marge (px)|Եզրային լուսանցք (px)|Margem (px)
Islands|Острова|孤岛|आइलैंड|Islas|الجزر|Îlots|Կղզիներ|Ilhas
Selected|Выбранные|已选|चयनित|Seleccionadas|المحددة|Sélectionnés|Ընտրված|Selecionadas
All visible|Все видимые|所有可见|सभी दृश्यमान|Todas las visibles|كل المرئية|Tous les visibles|Բոլոր տեսանելիները|Todas as visíveis
Passes|Проходы|轮数|प्रयास|Pasadas|المحاولات|Passes|Փորձեր|Passadas
Compute|Вычисления|计算|गणना|Cálculo|الحساب|Calcul|Հաշվարկ|Processamento
Automatic|Авто|自动|स्वचालित|Automático|تلقائي|Automatique|Ավտոմատ|Automático
Blender GPU|GPU Blender|Blender GPU|Blender GPU|GPU de Blender|GPU في Blender|GPU de Blender|Blender-ի GPU|GPU do Blender
Overall scale|Общий масштаб|整体缩放|समग्र स्केल|Escala global|المقياس العام|Échelle globale|Ընդհանուր մասշտաբ|Escala global
Tolerance|Допуск|容差|सहनशीलता|Tolerancia|السماحية|Tolérance|Շեղման թույլատրելի սահման|Tolerância
Pack Islands|Упаковать острова|打包孤岛|आइलैंड पैक करें|Empaquetar islas|رتّب الجزر|Empaqueter les îlots|Փաթեթավորել կղզիները|Empacotar ilhas
Select Similar|Выбрать схожие|选择相似项|समान आइलैंड चुनें|Seleccionar similares|حدد الجزر المتشابهة|Sélectionner les îlots similaires|Ընտրել նմանները|Selecionar semelhantes
Snap|Snap|重合|स्नैप करें|Superponer|طابق الجزر|Superposer|Համատեղել|Sobrepor
Clear Snap|Снять Snap|取消重合|स्नैप हटाएँ|Deshacer superposición|ألغِ المطابقة|Dissocier la superposition|Չեղարկել համատեղումը|Desfazer sobreposição
Locks|Фиксации|锁定|लॉक|Bloqueos|الأقفال|Verrouillages|Ամրագրումներ|Bloqueios
Rotation|Поворот|旋转|घुमाव|Rotación|الدوران|Rotation|Պտույտ|Rotação
Size|Размер|大小|आकार|Tamaño|الحجم|Taille|Չափ|Tamanho
Position|Положение|位置|स्थिति|Posición|الموضع|Position|Դիրք|Posição
UV Clusters|Кластеры UV|UV 组|UV क्लस्टर|Clústeres UV|مجموعات UV|Groupes UV|UV խմբեր|Grupos UV
Cluster / islands|Кластер / острова|组 / 孤岛|क्लस्टर / आइलैंड|Clúster / islas|المجموعة / الجزر|Groupe / îlots|Խումբ / կղզիներ|Grupo / ilhas
Cluster {id}|Кластер {id}|组 {id}|क्लस्टर {id}|Clúster {id}|المجموعة {id}|Groupe {id}|Խումբ {id}|Grupo {id}
Refresh List|Обновить список|刷新列表|सूची रीफ़्रेश करें|Actualizar lista|حدّث القائمة|Actualiser la liste|Թարմացնել ցուցակը|Atualizar lista
Merge into Cluster|Объединить в кластер|合并为组|क्लस्टर में मिलाएँ|Unir en clúster|ادمج في مجموعة|Fusionner dans un groupe|Միավորել խմբում|Unir em grupo
Select Cluster|Выделить кластер|选择组|क्लस्टर चुनें|Seleccionar clúster|حدد المجموعة|Sélectionner le groupe|Ընտրել խումբը|Selecionar grupo
Remove Selected|Убрать выделенные|移除选中项|चुने हुए हटाएँ|Quitar selección del clúster|أزل الجزر المحددة|Retirer les îlots sélectionnés|Հեռացնել ընտրվածները|Remover selecionadas
Disband Cluster|Расформировать|解散组|क्लस्टर अलग करें|Disolver clúster|فك المجموعة|Dissoudre le groupe|Լուծարել խումբը|Desfazer grupo
UV Stretch|Растяжение UV|UV 拉伸|UV खिंचाव|Estiramiento UV|تمدد UV|Étirement UV|UV ձգում|Alongamento UV
Threshold|Порог|阈值|सीमा|Umbral|الحد|Seuil|Շեմ|Limite
Find Stretched Islands|Найти растянутые острова|查找拉伸孤岛|खिंचे हुए आइलैंड खोजें|Buscar islas estiradas|ابحث عن الجزر المتمددة|Rechercher les îlots étirés|Գտնել ձգված կղզիները|Encontrar ilhas alongadas
Toggle Ignore|Переключить игнорирование|切换忽略|अनदेखा करें या वापस जोड़ें|Alternar exclusión|بدّل التجاهل|Basculer l’exclusion|Փոխել անտեսման վիճակը|Alternar exclusão
Island / stretch / ignore|Остров / растяжение / игнор|孤岛 / 拉伸 / 忽略|आइलैंड / खिंचाव / अनदेखा|Isla / estiramiento / exclusión|الجزيرة / التمدد / التجاهل|Îlot / étirement / exclusion|Կղզի / ձգում / անտեսում|Ilha / alongamento / exclusão
UV Diagnostics|Диагностика UV|UV 诊断|UV जाँच|Diagnóstico UV|تشخيص UV|Diagnostic UV|UV ախտորոշում|Diagnóstico UV
Find Stray Vertices|Найти лишние вершины|查找冗余顶点|अतिरिक्त शीर्ष खोजें|Buscar vértices sobrantes|ابحث عن الرؤوس الزائدة|Rechercher les sommets superflus|Գտնել ավելորդ գագաթները|Encontrar vértices redundantes
Find UV Self-Intersections|Найти самопересечения UV|查找 UV 自相交|UV स्व-प्रतिच्छेदन खोजें|Buscar autointersecciones UV|ابحث عن التقاطعات الذاتية في UV|Rechercher les auto-intersections UV|Գտնել UV ինքնահատումները|Encontrar autointerseções UV
Angle tolerance|Угловой допуск|角度容差|कोण सहनशीलता|Tolerancia angular|السماحية الزاوية|Tolérance angulaire|Անկյունային շեղման սահման|Tolerância angular
Vertices found: {count}|Найдено вершин: {count}|找到顶点：{count}|मिले शीर्ष: {count}|Vértices encontrados: {count}|الرؤوس الموجودة: {count}|Sommets trouvés : {count}|Գտնված գագաթներ՝ {count}|Vértices encontrados: {count}
Islands found: {count}|Найдено островов: {count}|找到孤岛：{count}|मिले आइलैंड: {count}|Islas encontradas: {count}|الجزر الموجودة: {count}|Îlots trouvés : {count}|Գտնված կղզիներ՝ {count}|Ilhas encontradas: {count}
Found: {count}. Selected: {selected}|Найдено: {count}. Выделено: {selected}|找到：{count}，已选：{selected}|मिले: {count}। चुने: {selected}|Encontradas: {count}. Seleccionadas: {selected}|الموجودة: {count}. المحددة: {selected}|Trouvés : {count}. Sélectionnés : {selected}|Գտնվել է՝ {count}։ Ընտրվել է՝ {selected}|Encontradas: {count}. Selecionadas: {selected}
Islands added to selection: {count}|Добавлено островов к выделению: {count}|已加入选择：{count}|चयन में जोड़े गए आइलैंड: {count}|Islas añadidas a la selección: {count}|الجزر المضافة إلى التحديد: {count}|Îlots ajoutés à la sélection : {count}|Ընտրությանը ավելացված կղզիներ՝ {count}|Ilhas adicionadas à seleção: {count}
No similar islands found.|Дополнительные острова в пределах допуска не найдены|未找到相似孤岛。|कोई समान आइलैंड नहीं मिला।|No se encontraron islas similares.|لم تُعثر على جزر مشابهة.|Aucun îlot similaire trouvé.|Նման կղզիներ չեն գտնվել։|Nenhuma ilha semelhante encontrada.
Select an island with a closed UV outline.|Выделите остров с замкнутым UV-контуром|选择具有闭合 UV 轮廓的孤岛。|बंद UV रूपरेखा वाला आइलैंड चुनें।|Selecciona una isla con contorno UV cerrado.|حدد جزيرة ذات محيط UV مغلق.|Sélectionnez un îlot au contour UV fermé.|Ընտրեք փակ UV եզրագծով կղզի։|Selecione uma ilha com contorno UV fechado.
Select an available UV island.|Выделите доступный UV-остров|选择一个可用的 UV 孤岛。|एक उपलब्ध UV आइलैंड चुनें।|Selecciona una isla UV disponible.|حدد جزيرة UV متاحة.|Sélectionnez un îlot UV disponible.|Ընտրեք հասանելի UV կղզի։|Selecione uma ilha UV disponível.
Select an available cluster in the list.|Выберите доступный кластер в таблице|在列表中选择可用的组。|सूची में उपलब्ध क्लस्टर चुनें।|Selecciona un clúster disponible en la lista.|حدد مجموعة متاحة في القائمة.|Sélectionnez un groupe disponible dans la liste.|Ցուցակում ընտրեք հասանելի խումբ։|Selecione um grupo disponível na lista.
Run the stretch check first.|Сначала найдите растянутые острова|请先运行拉伸检查。|पहले खिंचाव की जाँच करें।|Ejecuta primero el análisis de estiramiento.|شغّل فحص التمدد أولًا.|Lancez d’abord la recherche d’étirement.|Նախ ստուգեք ձգումը։|Execute primeiro a análise de alongamento.
Preparing layout|Подготовка раскладки|正在准备布局|लेआउट तैयार हो रहा है|Preparando la distribución|جارٍ إعداد التوزيع|Préparation de la disposition|Դասավորության նախապատրաստում|Preparando a distribuição
Retrying on CPU|Повтор на CPU|正在使用 CPU 重试|CPU पर पुनः प्रयास|Reintentando en CPU|إعادة المحاولة على CPU|Nouvel essai sur CPU|Կրկին փորձել CPU-ով|Tentando novamente na CPU
Compacting|Уплотнение|正在紧凑排列|लेआउट सघन किया जा रहा है|Compactando|جارٍ الضغط|Optimisation de l’espace|Դասավորության խտացում|Compactando
Pass {current}/{total}|Проход {current}/{total}|第 {current}/{total} 轮|प्रयास {current}/{total}|Pasada {current}/{total}|المحاولة {current}/{total}|Passe {current}/{total}|Փորձ {current}/{total}|Passada {current}/{total}
Packing cancelled|Упаковка отменена|打包已取消|पैकिंग रद्द हुई|Empaquetado cancelado|أُلغي الترتيب|Empaquetage annulé|Փաթեթավորումը չեղարկվել է|Empacotamento cancelado
Esc to cancel|Esc — отменить|Esc 取消|रद्द करने के लिए Esc|Esc para cancelar|Esc للإلغاء|Échap pour annuler|Esc՝ չեղարկելու համար|Esc para cancelar
Fill ≈ {fill} · scale ×{scale}|Заполнение ≈ {fill} · масштаб ×{scale}|填充率 ≈ {fill} · 缩放 ×{scale}|भराव ≈ {fill} · स्केल ×{scale}|Ocupación ≈ {fill} · escala ×{scale}|الإشغال ≈ {fill} · المقياس ×{scale}|Remplissage ≈ {fill} · échelle ×{scale}|Լցվածք ≈ {fill} · մասշտաբ ×{scale}|Ocupação ≈ {fill} · escala ×{scale}
Groups skipped: {count}|Пропущено групп: {count}|已跳过的组：{count}|छोड़े गए समूह: {count}|Grupos omitidos: {count}|المجموعات المتخطاة: {count}|Groupes ignorés : {count}|Բաց թողնված խմբեր՝ {count}|Grupos ignorados: {count}
CPU fallback: {reason}|Переход на CPU: {reason}|已回退到 CPU：{reason}|CPU का उपयोग: {reason}|Alternativa en CPU: {reason}|الرجوع إلى CPU: {reason}|Repli sur CPU : {reason}|Անցում CPU-ի՝ {reason}|Alternativa na CPU: {reason}
No layout found. Check the locks and padding.|Раскладка не найдена. Проверьте фиксации и минимальные отступы.|未找到布局。请检查锁定和间距。|कोई लेआउट नहीं मिला। लॉक और अंतर जाँचें।|No se encontró una distribución. Revisa los bloqueos y márgenes.|لم يُعثر على توزيع. تحقّق من الأقفال والتباعد.|Aucune disposition trouvée. Vérifiez les verrouillages et les marges.|Դասավորություն չի գտնվել։ Ստուգեք ամրագրումներն ու լուսանցքները։|Nenhuma distribuição encontrada. Verifique os bloqueios e as margens.
No available islands to pack. Check the selection and groups.|Нет доступных UV-островов для упаковки. Проверьте выделение, кластеры и Snap-группы|没有可打包的孤岛。请检查选择和分组。|पैक करने के लिए कोई आइलैंड नहीं है। चयन और समूह जाँचें।|No hay islas disponibles. Revisa la selección y los grupos.|لا توجد جزر متاحة للترتيب. تحقّق من التحديد والمجموعات.|Aucun îlot à empaqueter. Vérifiez la sélection et les groupes.|Փաթեթավորման համար հասանելի կղզիներ չկան։ Ստուգեք ընտրությունն ու խմբերը։|Nenhuma ilha disponível para empacotar. Verifique a seleção e os grupos.
Snap groups created: {count}|Создано Snap-групп: {count}|已创建重合组：{count}|बने स्नैप समूह: {count}|Grupos superpuestos creados: {count}|مجموعات المطابقة المنشأة: {count}|Groupes superposés créés : {count}|Ստեղծված համատեղ խմբեր՝ {count}|Grupos sobrepostos criados: {count}
Snap groups cleared: {count}|Расформировано Snap-групп: {count}|已解散重合组：{count}|हटाए गए स्नैप समूह: {count}|Grupos superpuestos disueltos: {count}|مجموعات المطابقة المفككة: {count}|Groupes superposés dissous : {count}|Լուծարված համատեղ խմբեր՝ {count}|Grupos sobrepostos desfeitos: {count}
Locked islands: {count}|Зафиксировано островов: {count}|已锁定孤岛：{count}|लॉक किए गए आइलैंड: {count}|Islas bloqueadas: {count}|الجزر المقفلة: {count}|Îlots verrouillés : {count}|Ամրագրված կղզիներ՝ {count}|Ilhas bloqueadas: {count}
Unlocked islands: {count}|Освобождено островов: {count}|已解锁孤岛：{count}|अनलॉक किए गए आइलैंड: {count}|Islas desbloqueadas: {count}|الجزر غير المقفلة: {count}|Îlots déverrouillés : {count}|Ազատված կղզիներ՝ {count}|Ilhas desbloqueadas: {count}
Select at least two available islands outside clusters.|Выделите хотя бы два доступных острова вне кластеров|请选择至少两个组外的可用孤岛。|क्लस्टर के बाहर कम से कम दो उपलब्ध आइलैंड चुनें।|Selecciona al menos dos islas disponibles fuera de los clústeres.|حدد جزيرتين متاحتين على الأقل خارج المجموعات.|Sélectionnez au moins deux îlots disponibles hors des groupes.|Ընտրեք խմբերից դուրս առնվազն երկու հասանելի կղզի։|Selecione pelo menos duas ilhas disponíveis fora dos grupos.
Select at least two islands or Snap groups.|Для кластера выделите хотя бы два острова или две Snap-группы|请至少选择两个孤岛或重合组。|कम से कम दो आइलैंड या स्नैप समूह चुनें।|Selecciona al menos dos islas o grupos superpuestos.|حدد جزيرتين أو مجموعتي مطابقة على الأقل.|Sélectionnez au moins deux îlots ou groupes superposés.|Ընտրեք առնվազն երկու կղզի կամ համատեղ խումբ։|Selecione pelo menos duas ilhas ou grupos sobrepostos.
Open all affected clusters and Snap groups.|Откройте все части затронутых кластеров и Snap-групп|请打开所有受影响的组和重合组。|सभी प्रभावित क्लस्टर और स्नैप समूह खोलें।|Abre todos los clústeres y grupos superpuestos afectados.|افتح كل المجموعات ومجموعات المطابقة المعنية.|Ouvrez tous les groupes et superpositions concernés.|Բացեք բոլոր առնչվող խմբերն ու համատեղ խմբերը։|Abra todos os grupos e sobreposições afetados.
Select islands that belong to a cluster.|Выделите острова, входящие в кластер|请选择属于某个组的孤岛。|क्लस्टर में शामिल आइलैंड चुनें।|Selecciona islas que pertenezcan a un clúster.|حدد الجزر التي تنتمي إلى مجموعة.|Sélectionnez des îlots appartenant à un groupe.|Ընտրեք խմբի մեջ մտնող կղզիները։|Selecione ilhas que pertençam a um grupo.
All selected islands already belong to this cluster.|Все выделенные острова уже входят в этот кластер|选中的孤岛都已属于该组。|सभी चुने आइलैंड पहले से इस क्लस्टर में हैं।|Todas las islas seleccionadas ya pertenecen al clúster.|كل الجزر المحددة تنتمي بالفعل إلى هذه المجموعة.|Tous les îlots sélectionnés appartiennent déjà à ce groupe.|Բոլոր ընտրված կղզիներն արդեն այս խմբում են։|Todas as ilhas selecionadas já pertencem a este grupo.
The island has changed or is hidden. Refresh the list.|Остров изменился или скрыт. Обновите таблицу|孤岛已更改或隐藏。请刷新列表。|आइलैंड बदल गया है या छिपा है। सूची रीफ़्रेश करें।|La isla ha cambiado o está oculta. Actualiza la lista.|تغيّرت الجزيرة أو أصبحت مخفية. حدّث القائمة.|L’îlot a changé ou est masqué. Actualisez la liste.|Կղզին փոխվել է կամ թաքնված է։ Թարմացրեք ցուցակը։|A ilha mudou ou está oculta. Atualize a lista.
No compatible matches found.|Допустимых совпадений нет.|未找到兼容的匹配项。|कोई मेल खाने वाला आइलैंड नहीं मिला।|No se encontraron coincidencias compatibles.|لم تُعثر على مطابقات متوافقة.|Aucune correspondance compatible trouvée.|Համատեղելի զույգեր չեն գտնվել։|Nenhuma correspondência compatível encontrada.
No available Snap groups. Open all members of the group.|Нет доступных Snap-групп. Для снятия Snap откройте все части группы|没有可用的重合组。请打开组内所有成员。|कोई उपलब्ध स्नैप समूह नहीं है। समूह के सभी सदस्य खोलें।|No hay grupos superpuestos disponibles. Abre todos sus miembros.|لا توجد مجموعات مطابقة متاحة. افتح كل عناصر المجموعة.|Aucun groupe superposé disponible. Ouvrez tous ses éléments.|Համատեղ խմբեր չկան։ Բացեք խմբի բոլոր անդամները։|Nenhum grupo sobreposto disponível. Abra todos os membros.
UV data changed. Start packing again.|UV-данные изменились во время поиска. Запустите упаковку снова|UV 数据已更改。请重新打包。|UV डेटा बदल गया। पैकिंग फिर शुरू करें।|Los datos UV cambiaron. Vuelve a empaquetar.|تغيّرت بيانات UV. ابدأ الترتيب من جديد.|Les données UV ont changé. Relancez l’empaquetage.|UV տվյալները փոխվել են։ Կրկին սկսեք փաթեթավորումը։|Os dados UV mudaram. Inicie o empacotamento novamente.
The layout failed the bounds, padding and lock checks.|Раскладка не прошла проверку границ, зазоров и фиксаций|布局未通过边界、间距和锁定检查。|लेआउट सीमा, अंतर और लॉक की जाँच में विफल रहा।|La distribución no superó la validación de bordes, márgenes y bloqueos.|لم يجتز التوزيع فحص الحدود والتباعد والأقفال.|La disposition a échoué aux vérifications des limites, marges et verrouillages.|Դասավորությունը չի անցել սահմանների, լուսանցքների և ամրագրումների ստուգումը։|A distribuição falhou nas verificações de bordas, margens e bloqueios.
The border takes up the entire UV tile.|Поле от края занимает весь UV-тайл|边距占据整个 UV 图块。|किनारे का अंतर पूरे UV टाइल को घेरता है।|El margen ocupa toda la tesela UV.|يشغل الهامش بلاطة UV بأكملها.|La marge occupe toute la tuile UV.|Լուսանցքը զբաղեցնում է ամբողջ UV սալիկը։|A margem ocupa todo o bloco UV.
The gap exceeds the shorter side of the texture.|Зазор превышает меньшую сторону текстуры|间距超过纹理的较短边。|अंतर टेक्सचर की छोटी भुजा से अधिक है।|La separación supera el lado más corto de la textura.|يتجاوز التباعد أقصر ضلع للنسيج.|L’espacement dépasse le côté court de la texture.|Միջակայքը գերազանցում է տեքստուրայի կարճ կողմը։|O espaçamento excede o lado menor da textura.
Set the number of passes to 1–1000.|Задайте от 1 до 1000 проходов|请将轮数设置为 1–1000。|प्रयासों की संख्या 1–1000 रखें।|Fija el número de pasadas entre 1 y 1000.|عيّن عدد المحاولات بين 1 و1000.|Choisissez entre 1 et 1000 passes.|Սահմանեք 1–1000 փորձ։|Defina entre 1 e 1000 passadas.
Invalid UV coordinates in {mesh}.|Некорректные UV-координаты в объекте {mesh}|{mesh} 中的 UV 坐标无效。|{mesh} में अमान्य UV निर्देशांक हैं।|Coordenadas UV no válidas en {mesh}.|إحداثيات UV غير صالحة في {mesh}.|Coordonnées UV invalides dans {mesh}.|Անվավեր UV կոորդինատներ՝ {mesh}։|Coordenadas UV inválidas em {mesh}.
Select available islands and open all group members.|Выделите доступные острова и откройте все части их групп|请选择可用的孤岛并打开组内所有成员。|उपलब्ध आइलैंड चुनें और समूह के सभी सदस्य खोलें।|Selecciona islas disponibles y abre todos los miembros de sus grupos.|حدد الجزر المتاحة وافتح كل عناصر مجموعاتها.|Sélectionnez les îlots disponibles et ouvrez tous les éléments de leurs groupes.|Ընտրեք հասանելի կղզիները և բացեք խմբի բոլոր անդամները։|Selecione ilhas disponíveis e abra todos os membros dos grupos.
Select redundant collinear vertices on N-gons|Выделить лишние вершины на прямых рёбрах N-гонов|选择多边面直边上的冗余顶点|एन-गॉन की सीधी धारों पर अतिरिक्त शीर्ष चुनें|Selecciona los vértices colineales sobrantes de los n-gonos|حدد الرؤوس الزائدة على الحواف المستقيمة للمضلعات متعددة الأضلاع|Sélectionner les sommets superflus sur les arêtes droites des n-gones|Ընտրել N-անկյունների ուղիղ կողերի ավելորդ գագաթները|Seleciona vértices colineares redundantes em n-gons
Select islands with crossed UV edges or overlapping UV faces|Выделить острова с пересекающимися UV-рёбрами или наложением граней|选择 UV 边交叉或面重叠的孤岛|कटी हुई UV धारों या ओवरलैप होते फ़ेस वाले आइलैंड चुनें|Selecciona islas con bordes UV cruzados o caras superpuestas|حدد الجزر ذات حواف UV متقاطعة أو أوجه متداخلة|Sélectionner les îlots dont les arêtes UV se croisent ou dont les faces se chevauchent|Ընտրել հատվող UV կողերով կամ ծածկվող նիստերով կղզիները|Seleciona ilhas com arestas UV cruzadas ou faces sobrepostas
Select visible islands with matching topology and nearby UV vertices|Выделить видимые острова с той же топологией и близкими UV-вершинами|选择拓扑一致且 UV 顶点接近的可见孤岛|समान टोपोलॉजी और पास के UV शीर्ष वाले दृश्यमान आइलैंड चुनें|Selecciona islas visibles con la misma topología y vértices UV próximos|حدد الجزر المرئية المتطابقة في البنية وذات رؤوس UV متقاربة|Sélectionner les îlots visibles de même topologie aux sommets UV proches|Ընտրել նույն տոպոլոգիայով և մոտ UV գագաթներով տեսանելի կղզիները|Seleciona ilhas visíveis com topologia igual e vértices UV próximos
Align selected islands and keep them together as a Snap group|Совместить выделенные острова в Snap-группу|对齐所选孤岛并保持为重合组|चयनित आइलैंड मिलाकर स्नैप समूह बनाएँ|Alinea las islas seleccionadas y mantenlas en un grupo superpuesto|حاذِ الجزر المحددة واحتفظ بها في مجموعة مطابقة|Aligner les îlots sélectionnés et les conserver en superposition|Համատեղել ընտրված կղզիները մեկ խմբում|Alinha as ilhas selecionadas e mantém um grupo sobreposto
Disband selected Snap groups|Расформировать выбранные Snap-группы|解散所选重合组|चयनित स्नैप समूह अलग करें|Disuelve los grupos superpuestos seleccionados|فك مجموعات المطابقة المحددة|Dissoudre les superpositions sélectionnées|Լուծարել ընտրված համատեղ խմբերը|Desfaz os grupos sobrepostos selecionados
Lock or unlock island rotation|Зафиксировать или освободить поворот острова|锁定或解锁孤岛旋转|आइलैंड का घुमाव लॉक या अनलॉक करें|Bloquea o desbloquea la rotación de la isla|اقفل دوران الجزيرة أو حرّره|Verrouiller ou déverrouiller la rotation de l’îlot|Ամրագրել կամ ազատել կղզու պտույտը|Bloqueia ou desbloqueia a rotação da ilha
Lock or unlock island size|Зафиксировать или освободить размер острова|锁定或解锁孤岛大小|आइलैंड का आकार लॉक या अनलॉक करें|Bloquea o desbloquea el tamaño de la isla|اقفل حجم الجزيرة أو حرّره|Verrouiller ou déverrouiller la taille de l’îlot|Ամրագրել կամ ազատել կղզու չափը|Bloqueia ou desbloqueia o tamanho da ilha
Lock or unlock the island center|Зафиксировать или освободить центр острова|锁定或解锁孤岛中心位置|आइलैंड का केंद्र लॉक या अनलॉक करें|Bloquea o desbloquea el centro de la isla|اقفل مركز الجزيرة أو حرّره|Verrouiller ou déverrouiller le centre de l’îlot|Ամրագրել կամ ազատել կղզու կենտրոնը|Bloqueia ou desbloqueia o centro da ilha
Find a dense layout in the 0–1 tile within padding and locks|Найти плотную раскладку в тайле 0–1 с учётом отступов и фиксаций|在 0–1 图块中查找符合间距和锁定条件的紧凑布局|अंतर और लॉक का पालन करते हुए 0–1 टाइल में सघन लेआउट खोजें|Busca una distribución densa en la tesela 0–1 respetando márgenes y bloqueos|ابحث عن توزيع مكثف في البلاطة 0–1 مع مراعاة التباعد والأقفال|Trouver une disposition dense dans la tuile 0–1 en respectant les marges et verrouillages|Գտնել խիտ դասավորություն 0–1 սալիկում՝ պահելով լուսանցքներն ու ամրագրումները|Busca uma distribuição densa no bloco 0–1 respeitando margens e bloqueios
List clusters on open UV maps|Показать кластеры открытых UV-карт|列出已打开 UV 贴图上的组|खुले UV मैप के क्लस्टर दिखाएँ|Muestra los clústeres de los mapas UV abiertos|اعرض المجموعات في خرائط UV المفتوحة|Afficher les groupes des cartes UV ouvertes|Ցուցադրել բաց UV քարտեզների խմբերը|Lista os grupos dos mapas UV abertos
Create a cluster or merge the selected islands and clusters|Создать кластер или объединить выделенные острова и кластеры|创建组或合并所选孤岛和组|क्लस्टर बनाएँ या चयनित आइलैंड और क्लस्टर मिलाएँ|Crea un clúster o une las islas y clústeres seleccionados|أنشئ مجموعة أو ادمج الجزر والمجموعات المحددة|Créer un groupe ou fusionner les îlots et groupes sélectionnés|Ստեղծել խումբ կամ միավորել ընտրված կղզիներն ու խմբերը|Cria um grupo ou une as ilhas e os grupos selecionados
Select the islands in this cluster|Выделить острова этого кластера|选择此组中的孤岛|इस क्लस्टर के आइलैंड चुनें|Selecciona las islas de este clúster|حدد الجزر في هذه المجموعة|Sélectionner les îlots de ce groupe|Ընտրել այս խմբի կղզիները|Seleciona as ilhas deste grupo
Remove selected islands from their clusters|Убрать выделенные острова из их кластеров|从组中移除所选孤岛|चयनित आइलैंड उनके क्लस्टर से हटाएँ|Quita las islas seleccionadas de sus clústeres|أزل الجزر المحددة من مجموعاتها|Retirer les îlots sélectionnés de leurs groupes|Հեռացնել ընտրված կղզիներն իրենց խմբերից|Remove as ilhas selecionadas de seus grupos
Separate all islands in this cluster|Разъединить все острова этого кластера|拆分此组中的所有孤岛|इस क्लस्टर के सभी आइलैंड अलग करें|Separa todas las islas de este clúster|افصل كل الجزر في هذه المجموعة|Séparer tous les îlots de ce groupe|Առանձնացնել այս խմբի բոլոր կղզիները|Separa todas as ilhas deste grupo
List visible islands at or above the stretch threshold|Показать видимые острова с растяжением от порога|列出拉伸达到阈值的可见孤岛|सीमा तक या उससे अधिक खिंचे दृश्यमान आइलैंड दिखाएँ|Lista las islas visibles que alcanzan o superan el umbral|اعرض الجزر المرئية التي يبلغ تمددها الحد أو يتجاوزه|Lister les îlots visibles dont l’étirement atteint ou dépasse le seuil|Ցուցադրել շեմին հասնող կամ այն գերազանցող ձգմամբ տեսանելի կղզիները|Lista as ilhas visíveis que atingem ou excedem o limite de alongamento
Keep this island in the report and toggle automatic selection|Оставить остров в отчёте и переключить автовыделение|保留报告中的孤岛并切换自动选择|आइलैंड को रिपोर्ट में रखें और स्वतः चयन टॉगल करें|Conserva la isla en el informe y alterna la selección automática|احتفظ بالجزيرة في التقرير وبدّل تحديدها التلقائي|Garder l’îlot dans le rapport et basculer la sélection automatique|Պահել կղզին հաշվետվության մեջ և փոխել ինքնաընտրումը|Mantém a ilha no relatório e alterna a seleção automática
"""

_CATALOG = {}
for _line in _STRINGS.strip().splitlines():
    _source, *_translations = _line.split("|")
    _CATALOG[_source] = dict(zip(_CODES, _translations, strict=True))


def language(context=None):
    prefs = _preferences(context or bpy.context)
    return prefs.language if prefs else "RU"


def _preferences(context):
    preferences = getattr(context, "preferences", None)
    addon = preferences.addons.get(__package__) if preferences else None
    return addon.preferences if addon else None


def draw_language(layout, context):
    prefs = _preferences(context)
    if prefs:
        layout.prop(prefs, "language", text=tr("Language"), translate=False)


def tr(source, *, locale=None, **values):
    text = _CATALOG.get(source, {}).get(locale or language(), source)
    return text.format(**values) if values else text


def enum_items(items):
    """Hold translated strings for RNA and preserve each stored numeric value."""
    cached = {
        code: [(identifier, tr(label, locale=code), tr(description, locale=code), number)
               for number, (identifier, label, description) in enumerate(items)]
        for code, _ in _LANGUAGES
    }

    def items_for_language(_settings, context):
        return cached[language(context)]

    return items_for_language


def _redraw(_settings, context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


class UVIT_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    language: EnumProperty(
        name="Language", default="RU",
        items=[(code, name, "") for code, name in _LANGUAGES], update=_redraw,
    )

    def draw(self, _context):
        self.layout.prop(self, "language", text=tr("Language"), translate=False)


def register():
    bpy.utils.register_class(UVIT_Preferences)


def unregister():
    bpy.utils.unregister_class(UVIT_Preferences)
