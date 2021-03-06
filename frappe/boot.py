# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals
"""
bootstrap client session
"""

import frappe
import frappe.defaults
import frappe.desk.desk_page
from frappe.desk.form.load import get_meta_bundle
from frappe.utils.change_log import get_versions
from frappe.translate import get_lang_dict
from frappe.email.inbox import get_email_accounts
from frappe.core.doctype.feedback_trigger.feedback_trigger import get_enabled_feedback_trigger

def get_bootinfo():
	"""build and return boot info"""
	frappe.set_user_lang(frappe.session.user)
	bootinfo = frappe._dict()
	hooks = frappe.get_hooks()
	doclist = []

	# user
	get_user(bootinfo)

	# system info
	bootinfo.sysdefaults = frappe.defaults.get_defaults()
	bootinfo.server_date = frappe.utils.nowdate()

	if frappe.session['user'] != 'Guest':
		bootinfo.user_info = get_fullnames()
		bootinfo.sid = frappe.session['sid'];

	bootinfo.modules = {}
	bootinfo.module_list = []
	load_desktop_icons(bootinfo)
	bootinfo.letter_heads = get_letter_heads()

	bootinfo.module_app = frappe.local.module_app
	bootinfo.single_types = frappe.db.sql_list("""select name from tabDocType
		where issingle=1""")
	add_home_page(bootinfo, doclist)
	bootinfo.page_info = get_allowed_pages()
	load_translations(bootinfo)
	add_timezone_info(bootinfo)
	load_conf_settings(bootinfo)
	load_print(bootinfo, doclist)
	doclist.extend(get_meta_bundle("Page"))
	bootinfo.home_folder = frappe.db.get_value("File", {"is_home_folder": 1})

	# ipinfo
	if frappe.session.data.get('ipinfo'):
		bootinfo.ipinfo = frappe.session['data']['ipinfo']

	# add docs
	bootinfo.docs = doclist

	for method in hooks.boot_session or []:
		frappe.get_attr(method)(bootinfo)

	if bootinfo.lang:
		bootinfo.lang = unicode(bootinfo.lang)
	bootinfo.versions = {k: v['version'] for k, v in get_versions().items()}

	bootinfo.error_report_email = frappe.get_hooks("error_report_email")
	bootinfo.calendars = sorted(frappe.get_hooks("calendars"))
	bootinfo.treeviews = frappe.get_hooks("treeviews") or []
	bootinfo.lang_dict = get_lang_dict()
	bootinfo.feedback_triggers = get_enabled_feedback_trigger()
	bootinfo.update(get_email_accounts(user=frappe.session.user))

	return bootinfo

def get_letter_heads():
	letter_heads = {}
	for letter_head in frappe.get_all("Letter Head", fields = ["name", "content"]):
		letter_heads.setdefault(letter_head.name, {'header': letter_head.content, 'footer': letter_head.footer})

	return letter_heads

def load_conf_settings(bootinfo):
	from frappe import conf
	bootinfo.max_file_size = conf.get('max_file_size') or 10485760
	for key in ('developer_mode', 'socketio_port'):
		if key in conf: bootinfo[key] = conf.get(key)

def load_desktop_icons(bootinfo):
	from frappe.desk.doctype.desktop_icon.desktop_icon import get_desktop_icons
	bootinfo.desktop_icons = get_desktop_icons()

def get_allowed_pages():
	return get_user_page_or_report('Page')

def get_allowed_reports():
	return get_user_page_or_report('Report')
	
def get_user_page_or_report(parent):
	roles = frappe.get_roles()
	has_role = {}
	field = "title" if parent == 'Page' else "name"
	
	# get pages or reports set on custom role
	for p in frappe.db.sql("""select `tabCustom Role`.{field} as name, `tabCustom Role`.modified
		from `tabCustom Role`, `tabHas Role` where
			`tabHas Role`.parent = `tabCustom Role`.name and
			`tabCustom Role`.{field} is not null and `tabHas Role`.role in ({roles})
			""".format(field=parent.lower(), roles = ', '.join(['%s']*len(roles))), roles, as_dict=1):

		has_role[p.name] = {"modified":p.modified, "title": p.name}
	
	if not has_role:
		for p in frappe.db.sql("""select distinct
			tab{parent}.name, tab{parent}.modified, tab{parent}.{field} as title
			from `tabHas Role`, `tab{parent}`
			where `tabHas Role`.role in ({roles})
				and `tabHas Role`.parent = `tab{parent}`.name
				""".format(parent=parent, field=field, roles = ', '.join(['%s']*len(roles))),
					roles, as_dict=True):

			has_role[p.name] = {"modified":p.modified, "title": p.title}

		# pages or reports where role is not set are also allowed
		for p in frappe.db.sql("""select name, modified, {field} as title
			from `tab{parent}` where
				(select count(*) from `tabHas Role`
					where `tabHas Role`.parent=tab{parent}.name) = 0""".format(parent=parent, field=field), as_dict=1):

			has_role[p.name] = {"modified":p.modified, "title": p.title}

	return has_role

def load_translations(bootinfo):
	messages = frappe.get_lang_dict("boot")

	bootinfo["lang"] = frappe.lang

	# load translated report names
	for name in bootinfo.user.all_reports:
		messages[name] = frappe._(name)

	# only untranslated
	messages = {k:v for k, v in messages.iteritems() if k!=v}

	bootinfo["__messages"] = messages

def get_fullnames():
	"""map of user fullnames"""
	ret = frappe.db.sql("""select name, full_name as fullname,
			user_image as image, gender, email, username
		from tabUser where enabled=1 and user_type!="Website User" """, as_dict=1)

	d = {}
	for r in ret:
		# if not r.image:
		# 	r.image = get_gravatar(r.name)
		d[r.name] = r

	return d

def get_user(bootinfo):
	"""get user info"""
	bootinfo.user = frappe.get_user().load_user()

def add_home_page(bootinfo, docs):
	"""load home page"""
	if frappe.session.user=="Guest":
		return
	home_page = frappe.db.get_default("desktop:home_page")

	if home_page == "setup-wizard":
		bootinfo.setup_wizard_requires = frappe.get_hooks("setup_wizard_requires")

	try:
		page = frappe.desk.desk_page.get(home_page)
	except (frappe.DoesNotExistError, frappe.PermissionError):
		if frappe.message_log:
			frappe.message_log.pop()
		page = frappe.desk.desk_page.get('desktop')

	bootinfo['home_page'] = page.name
	docs.append(page)

def add_timezone_info(bootinfo):
	system = bootinfo.sysdefaults.get("time_zone")
	import frappe.utils.momentjs
	bootinfo.timezone_info = {"zones":{}, "rules":{}, "links":{}}
	frappe.utils.momentjs.update(system, bootinfo.timezone_info)

def load_print(bootinfo, doclist):
	print_settings = frappe.db.get_singles_dict("Print Settings")
	print_settings.doctype = ":Print Settings"
	doclist.append(print_settings)
	load_print_css(bootinfo, print_settings)

def load_print_css(bootinfo, print_settings):
	bootinfo.print_css = frappe.get_attr("frappe.www.print.get_print_style")(print_settings.print_style or "Modern", for_legacy=True)

def get_unseen_notes():
	return frappe.db.sql('''select name, title, content from tabNote where notify_on_login=1
		and expire_notification_on > %s and %s not in
			(select user from `tabNote Seen By` nsb
				where nsb.parent=tabNote.name)''', (frappe.utils.now(), frappe.session.user), as_dict=True)