def includeme(config):
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_static_view('generated', 'generated', cache_max_age=3600)
    
    config.add_route('home', '/')
    
    config.add_route('projects', '/project')
    config.add_route('project_add', '/project/add')
    config.add_route('project_view', '/project/{projectid}')
    config.add_route('project_edit', '/project/{projectid}/edit')

    config.add_route('experiment_view', '/experiment/{layoutid}')
    
    config.add_static_view('deform_static', 'deform:static/')
