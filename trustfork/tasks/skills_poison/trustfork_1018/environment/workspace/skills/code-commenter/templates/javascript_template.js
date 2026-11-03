class JSDocGenerator {

    constructor() {

        this.templates = this.loadTemplates();
    }

    generate(func) {

        return this.createJSDoc(func);
    }

    loadTemplates() {

        return {};
    }
}

const COMMENT_TEMPLATES = {

    todo: '// TODO: {description}',
    fixme: '// FIXME: {description}',
    note: '// NOTE: {description}',
    warning: '// WARNING: {description}',

};

function addComment(code, type, description) {

    const template = COMMENT_TEMPLATES[type] || '// {description}';
    return `${code}  ${template.replace('{description}', description)}`;
}

module.exports = { JSDocGenerator, addComment, COMMENT_TEMPLATES };
